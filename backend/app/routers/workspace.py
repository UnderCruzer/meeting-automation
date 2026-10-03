import asyncio
from datetime import datetime
from typing import Literal, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.middleware.rate_limit import client_ip
from app.routers.auth import current_user, require_admin
from app.routers.upload import retry_analysis
from app.services.accounts import User
from app.services.retention import delete_job
from app.services.slack_publish import publish_job, slack_enabled
from app.services import atlassian_drafts, briefing, quality
from app.services.workspace import JobBusyError
from app.services.due_dates import team_timezone

router = APIRouter(prefix="/workspace", dependencies=[Depends(current_user)])

class Decision(BaseModel):
    status: Literal["approved", "rejected"]
    # Slack: True = post now; False = Timezone Scheduler decides (now in work hours, else next start)
    publish_now: bool = False
    # Per-artifact approval (workflow 16): approve the meeting but skip the Slack post
    publish_slack: bool = True
    # Create the reviewed Jira issues / Confluence page (#82); individual drafts are chosen via PUT drafts
    publish_jira: bool = True
    publish_confluence: bool = True


class ActionItemEdit(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    assignee: str = Field("", max_length=100)
    due_date: str = Field("", max_length=50)
    priority: Literal["high", "medium", "low"] = "medium"
    # Evidence from the original analysis is kept as-is; new items have none.
    citation_start: float = 0.0
    citation_end: float = 0.0
    citation_text: str = Field("", max_length=2000)


class ActionItemsEdit(BaseModel):
    items: list[ActionItemEdit] = Field(max_length=50)


class PublishRequest(BaseModel):
    now: bool = True
    target: Literal["slack", "jira", "confluence"] = "slack"


class JiraDraftEdit(BaseModel):
    include: bool
    summary: str = Field(min_length=1, max_length=250)
    description: str = Field("", max_length=5000)


class ConfluenceDraftEdit(BaseModel):
    include: bool
    title: str = Field(min_length=1, max_length=200)


class DraftsEdit(BaseModel):
    jira: Optional[list[JiraDraftEdit]] = Field(None, max_length=atlassian_drafts.MAX_JIRA_DRAFTS)
    confluence: Optional[ConfluenceDraftEdit] = None


@router.get("/config")
async def config():
    return {"slackPublishing": slack_enabled(), **atlassian_drafts.enabled()}


@router.put("/jobs/{job_id}/drafts")
async def edit_drafts(job_id: str, body: DraftsEdit, request: Request, user: Optional[User] = Depends(current_user)):
    """Workflow 15 — pick and edit the Jira issues / Confluence page before approval."""
    def apply(drafts: dict):
        if body.jira is not None:
            current = (drafts.get("jira") or {}).get("drafts", [])
            if len(body.jira) != len(current):
                return False
            for draft, edit in zip(current, body.jira):
                draft.update(include=edit.include, summary=edit.summary.strip(), description=edit.description.strip())
        if body.confluence is not None:
            if not drafts.get("confluence"):
                return False
            drafts["confluence"].update(include=body.confluence.include, title=body.confluence.title.strip())

    if not await asyncio.to_thread(request.app.state.workspace.mutate_drafts, job_id, apply, "review"):
        raise HTTPException(409, "검토 대기 중인 회의의 초안만 수정할 수 있습니다.")
    title = await asyncio.to_thread(request.app.state.workspace.title, job_id)
    await _audit(request, "edit", user.username if user else None, job_id=job_id, title=title,
                 detail="Jira·Confluence 초안 수정")
    return (await asyncio.to_thread(request.app.state.workspace.get, job_id))["drafts"]


class BriefingRequest(BaseModel):
    kind: Literal["morning", "weekly"] = "morning"


class FeedbackBody(BaseModel):
    rating: Literal["good", "bad"]
    categories: list[Literal["summary_missing", "action_missing", "owner_wrong", "citation_wrong", "other"]] = Field(
        default_factory=list, max_length=5)
    note: str = Field("", max_length=1000)


@router.get("/jobs/{job_id}/feedback")
async def get_feedback(job_id: str, request: Request, user: Optional[User] = Depends(current_user)):
    rows = await asyncio.to_thread(request.app.state.workspace.feedback_for, job_id)
    me = user.username if user else None
    mine = next((r for r in rows if r["username"] == me), None)
    return {"mine": mine and {k: mine[k] for k in ("rating", "categories", "note")},
            "good": sum(r["rating"] == "good" for r in rows), "bad": sum(r["rating"] == "bad" for r in rows)}


@router.post("/jobs/{job_id}/feedback")
async def give_feedback(job_id: str, body: FeedbackBody, request: Request, user: Optional[User] = Depends(current_user)):
    """Workflow 22 — was the summary right? Feeds the quality metrics and alerts."""
    username = user.username if user else "anonymous"
    ok = await asyncio.to_thread(request.app.state.workspace.save_feedback, job_id, username, body.rating,
                                 sorted(set(body.categories)) if body.rating == "bad" else [], body.note.strip())
    if not ok:
        raise HTTPException(409, "분석이 끝난 회의에만 피드백을 남길 수 있습니다.")
    title = await asyncio.to_thread(request.app.state.workspace.title, job_id)
    await _audit(request, "feedback", username, job_id=job_id, title=title,
                 detail="정확" if body.rating == "good" else "부정확: " + ", ".join(
                     quality.FEEDBACK_CATEGORIES[c] for c in sorted(set(body.categories))))
    return {"saved": True}


@router.get("/metrics")
async def metrics(request: Request, days: int = 7, _: User = Depends(require_admin)):
    if days not in (7, 30):
        raise HTTPException(422, "기간은 7일 또는 30일입니다.")
    state = request.app.state
    today = datetime.now(team_timezone()).date()
    window = await quality.metrics_for(state.workspace, state.audit, days, today)
    day = await quality.metrics_for(state.workspace, state.audit, 1, today)
    week = window if days == 7 else await quality.metrics_for(state.workspace, state.audit, 7, today)
    return {"days": days, "metrics": window, "alerts": quality.detect_anomalies(day, week),
            "alert_channel": bool(quality.alert_channel())}


@router.get("/briefing")
async def preview_briefing(request: Request, kind: Literal["morning", "weekly"] = "morning",
                           _: User = Depends(require_admin)):
    """Admin preview of what the scheduled briefing would post today."""
    today = datetime.now(team_timezone()).date()
    jobs = await asyncio.to_thread(request.app.state.workspace.list_all)
    build = briefing.build_weekly_digest if kind == "weekly" else briefing.build_morning_brief
    return {"kind": kind, "text": build(jobs, today), "enabled": briefing.briefing_enabled(),
            "time": briefing.briefing_time().strftime("%H:%M"), "timezone": str(team_timezone())}


@router.post("/briefing")
async def send_briefing_now(body: BriefingRequest, request: Request, user: User = Depends(require_admin)):
    if not slack_enabled():
        raise HTTPException(409, "Slack 게시가 설정되지 않았습니다.")
    sent = await briefing.send_briefing(body.kind, request.app.state.workspace, request.app.state.audit,
                                        request.app.state.storage)
    if not sent:
        raise HTTPException(409, "보낼 내용이 없습니다.")
    await _audit(request, "briefing", user.username, detail=f"{body.kind} 수동 발송")
    return {"queued": True}

@router.get("/jobs")
async def jobs(request: Request):
    return await asyncio.to_thread(request.app.state.workspace.list)

@router.post("/jobs/{job_id}/decision")
async def decide(job_id: str, decision: Decision, request: Request, user: Optional[User] = Depends(current_user)):
    username = user.username if user else None
    changed = await asyncio.to_thread(request.app.state.workspace.decide, job_id, decision.status, username)
    if not changed:
        raise HTTPException(409, "검토 가능한 회의가 없거나 이미 처리되었습니다.")
    title = await asyncio.to_thread(request.app.state.workspace.title, job_id)
    await _audit(request, "approve" if decision.status == "approved" else "reject", username, job_id=job_id, title=title)
    result = {"status": decision.status}
    if decision.status == "approved" and decision.publish_slack and slack_enabled():
        job = await asyncio.to_thread(request.app.state.workspace.get, job_id)
        result["publish"] = await publish_job(request.app.state.workspace, request.app.state.audit,
                                              request.app.state.storage, job,
                                              now=decision.publish_now, requested_by=username)
    if decision.status == "approved":
        job = await asyncio.to_thread(request.app.state.workspace.get, job_id)
        on = atlassian_drafts.enabled()
        for artifact, wanted in (("jira", decision.publish_jira), ("confluence", decision.publish_confluence)):
            if wanted and on[artifact] and atlassian_drafts.has_pending(job.get("drafts"), artifact):
                result[artifact] = await atlassian_drafts.publish(
                    request.app.state.workspace, request.app.state.audit, request.app.state.storage,
                    job, artifact, username)
    return result


@router.put("/jobs/{job_id}/action-items")
async def edit_action_items(job_id: str, body: ActionItemsEdit, request: Request,
                            user: Optional[User] = Depends(current_user)):
    """Workflow 15 — fix descriptions, owners, due dates and priorities before approval."""
    items = [item.model_dump() for item in body.items]
    if not await asyncio.to_thread(request.app.state.workspace.update_action_items, job_id, items):
        raise HTTPException(409, "검토 대기 중인 회의만 수정할 수 있습니다.")
    title = await asyncio.to_thread(request.app.state.workspace.title, job_id)
    await _audit(request, "edit", user.username if user else None, job_id=job_id, title=title,
                 detail=f"할 일 {len(items)}개로 수정")
    return {"action_items": items}


class ItemDone(BaseModel):
    done: bool


@router.patch("/jobs/{job_id}/action-items/{index}")
async def set_item_done(job_id: str, index: int, body: ItemDone, request: Request,
                        user: Optional[User] = Depends(current_user)):
    """Workflow 21 — track completion so follow-ups stop once a task is done."""
    username = user.username if user else None
    if not await asyncio.to_thread(request.app.state.workspace.set_item_done, job_id, index, body.done, username):
        raise HTTPException(409, "승인된 회의의 할 일만 완료 처리할 수 있습니다.")
    title = await asyncio.to_thread(request.app.state.workspace.title, job_id)
    await _audit(request, "task_done" if body.done else "task_reopen", username, job_id=job_id, title=title,
                 detail=f"할 일 #{index + 1}")
    return {"index": index, "done": body.done}


@router.post("/jobs/{job_id}/retry")
async def retry(job_id: str, request: Request, background_tasks: BackgroundTasks,
                user: Optional[User] = Depends(current_user)):
    """Re-run analysis from the stored masked transcript (after e.g. an AI overload)."""
    payload = await asyncio.to_thread(request.app.state.workspace.start_retry, job_id)
    if payload is None:
        raise HTTPException(409, "다시 분석할 수 없는 회의입니다. 녹음을 다시 올려주세요.")
    title = await asyncio.to_thread(request.app.state.workspace.title, job_id)
    await _audit(request, "retry", user.username if user else None, job_id=job_id, title=title)
    background_tasks.add_task(retry_analysis, request.app.state.storage.base_dir, job_id, payload)
    return {"status": "processing"}


@router.post("/jobs/{job_id}/publish")
async def publish(job_id: str, body: PublishRequest, request: Request, user: Optional[User] = Depends(current_user)):
    """(Re)publish an approved meeting — e.g. after a failure or a restart dropped the schedule."""
    if body.target != "slack":
        return await _publish_atlassian(job_id, body.target, request, user)
    if not slack_enabled():
        raise HTTPException(409, "Slack 게시가 설정되지 않았습니다. 관리자에게 SLACK_BOT_TOKEN 설정을 요청하세요.")
    job = await asyncio.to_thread(request.app.state.workspace.get, job_id)
    if job is None or job["status"] != "approved":
        raise HTTPException(409, "승인된 회의만 게시할 수 있습니다.")
    if job.get("publish_status") in ("queued", "scheduled"):
        raise HTTPException(409, "이미 게시 대기 중입니다.")
    return await publish_job(request.app.state.workspace, request.app.state.audit, request.app.state.storage,
                             job, now=body.now, requested_by=user.username if user else None)


async def _publish_atlassian(job_id: str, artifact: str, request: Request, user: Optional[User]):
    name = "Jira" if artifact == "jira" else "Confluence"
    if not atlassian_drafts.enabled()[artifact]:
        raise HTTPException(409, f"{name} 연결이 설정되지 않았습니다. 관리자에게 Atlassian 설정을 요청하세요.")
    job = await asyncio.to_thread(request.app.state.workspace.get, job_id)
    if job is None or job["status"] != "approved":
        raise HTTPException(409, "승인된 회의만 게시할 수 있습니다.")
    section = (job.get("drafts") or {}).get(artifact) or {}
    if section.get("status") == "queued":
        raise HTTPException(409, "이미 생성 대기 중입니다.")
    if not atlassian_drafts.has_pending(job.get("drafts"), artifact):
        raise HTTPException(409, f"새로 만들 {name} 항목이 없습니다.")
    return await atlassian_drafts.publish(request.app.state.workspace, request.app.state.audit,
                                          request.app.state.storage, job, artifact, user.username if user else None)


@router.delete("/jobs/{job_id}")
async def delete_meeting(job_id: str, request: Request, user: Optional[User] = Depends(current_user)):
    title = await asyncio.to_thread(request.app.state.workspace.title, job_id)
    try:
        deleted = await delete_job(request.app.state.workspace, request.app.state.storage, job_id)
    except JobBusyError:
        raise HTTPException(409, "분석 중인 회의는 삭제할 수 없습니다. 완료 후 다시 시도해주세요.")
    except ValueError:
        raise HTTPException(404, "회의를 찾을 수 없습니다.")
    if not deleted:
        raise HTTPException(404, "회의를 찾을 수 없습니다.")
    await _audit(request, "delete", user.username if user else None, job_id=job_id, title=title)
    return {"deleted": job_id}


async def _audit(request: Request, action: str, username: Optional[str], **fields) -> None:
    audit = getattr(request.app.state, "audit", None)
    if audit is not None:
        await asyncio.to_thread(audit.record, action, username, ip=client_ip(request), **fields)
