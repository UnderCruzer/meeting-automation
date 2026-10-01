import asyncio
from typing import Literal, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.middleware.rate_limit import client_ip
from app.routers.auth import current_user
from app.routers.upload import retry_analysis
from app.services.accounts import User
from app.services.retention import delete_job
from app.services.slack_publish import publish_job, slack_enabled
from app.services.workspace import JobBusyError

router = APIRouter(prefix="/workspace", dependencies=[Depends(current_user)])

class Decision(BaseModel):
    status: Literal["approved", "rejected"]
    # Slack: True = post now; False = Timezone Scheduler decides (now in work hours, else next start)
    publish_now: bool = False
    # Per-artifact approval (workflow 16): approve the meeting but skip the Slack post
    publish_slack: bool = True


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


@router.get("/config")
async def config():
    return {"slackPublishing": slack_enabled()}

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
    if not slack_enabled():
        raise HTTPException(409, "Slack 게시가 설정되지 않았습니다. 관리자에게 SLACK_BOT_TOKEN 설정을 요청하세요.")
    job = await asyncio.to_thread(request.app.state.workspace.get, job_id)
    if job is None or job["status"] != "approved":
        raise HTTPException(409, "승인된 회의만 게시할 수 있습니다.")
    if job.get("publish_status") in ("queued", "scheduled"):
        raise HTTPException(409, "이미 게시 대기 중입니다.")
    return await publish_job(request.app.state.workspace, request.app.state.audit, request.app.state.storage,
                             job, now=body.now, requested_by=user.username if user else None)


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
