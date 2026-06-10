"""
Review & Approval API.

POST /review/send   — send Slack review message for a job
POST /review/approve — approve or reject a single artifact
GET  /review/{job_id} — get current approval state
"""
import json
import logging
import os
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.services.approval_store import (
    all_resolved,
    approve_artifact,
    approved_artifacts,
    get_job,
    register_job,
    reject_artifact,
)
from app.services.write_queue import WriteTask, enqueue

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/review")


# ── Request / Response schemas ───────────────────────────────────────────────

class SendReviewRequest(BaseModel):
    job_id: str
    meeting_id: str
    file_key: str
    routing: list[str]   # ["jira", "confluence", "slack"]
    has_pii: bool = False
    summary_ko: str = ""
    quality_ok: bool = True


class ApproveRequest(BaseModel):
    job_id: str
    artifact: str        # "jira" | "confluence" | "slack"
    action: str          # "approve" | "reject"
    approved_by: str = ""
    schedule_time: str = ""


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/send")
async def send_review(req: SendReviewRequest, request: Request):
    """Register job (if not already registered) and send a Slack review message."""
    # fix: avoid re-registering an existing job (pipeline already called register_job
    # via send_review_message; calling it again would reset artifact statuses to pending)
    job = get_job(req.job_id)
    if job is None:
        job = register_job(req.job_id, req.meeting_id, req.routing)

    ts = await _send_slack_review(req)
    if ts:
        job.slack_review_ts = ts

    return {"job_id": req.job_id, "slack_ts": ts}


@router.post("/approve")
async def approve(req: ApproveRequest, request: Request):
    """Approve or reject one artifact. Triggers WriteQueue when all resolved."""
    if req.action == "approve":
        ok = approve_artifact(req.job_id, req.artifact, req.approved_by, req.schedule_time)
    elif req.action == "reject":
        ok = reject_artifact(req.job_id, req.artifact)
    else:
        raise HTTPException(status_code=422, detail=f"Unknown action: {req.action}")

    if not ok:
        raise HTTPException(status_code=404, detail=f"job_id {req.job_id!r} or artifact {req.artifact!r} not found")

    # Trigger write queue for approved artifacts when all decisions are made
    if all_resolved(req.job_id):
        storage = request.app.state.storage
        base_dir: Path = storage.base_dir
        job = get_job(req.job_id)

        for artifact_approval in approved_artifacts(req.job_id):
            # Try to load draft payload from disk
            payload = _load_draft(base_dir, job, artifact_approval.artifact)
            if payload:
                await enqueue(WriteTask(
                    job_id=req.job_id,
                    meeting_id=job.meeting_id,
                    artifact=artifact_approval.artifact,
                    payload=payload,
                    base_dir=base_dir,
                    schedule_time=artifact_approval.schedule_time,
                ))

        await _update_slack_review(job.slack_review_ts, req.job_id)

    return {"job_id": req.job_id, "artifact": req.artifact, "action": req.action}


@router.get("/{job_id}")
async def get_review_state(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"job_id {job_id!r} not found")
    return {
        "job_id": job.job_id,
        "meeting_id": job.meeting_id,
        "artifacts": {k: v.__dict__ for k, v in job.artifacts.items()},
        "all_resolved": all_resolved(job_id),
    }


# ── Slack helpers ─────────────────────────────────────────────────────────────

async def _send_slack_review(req: SendReviewRequest) -> str:
    token = os.getenv("SLACK_BOT_TOKEN", "")
    channel = os.getenv("SLACK_REVIEW_CHANNEL", os.getenv("SLACK_BRIEF_CHANNEL", "general"))
    if not token:
        logger.warning("[Review] SLACK_BOT_TOKEN not set — skipping review message")
        return ""

    pii_warning = "\n:warning: *민감정보가 감지되었습니다.* 초안을 꼭 검토해주세요." if req.has_pii else ""
    quality_note = "" if req.quality_ok else "\n:x: *품질 경고* — 요약 신뢰도가 낮습니다."

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "📋 회의 초안 검토 요청"}},
        {"type": "section", "text": {"type": "mrkdwn",
                                      "text": f"*회의 ID:* `{req.meeting_id}`{pii_warning}{quality_note}\n\n{req.summary_ko[:300]}"}},
        {"type": "divider"},
    ]

    for artifact in req.routing:
        blocks.append({
            "type": "actions",
            "block_id": f"approval_{artifact}_{req.job_id}",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": f"✅ {artifact.upper()} 승인"},
                 "style": "primary", "value": f"approve|{req.job_id}|{artifact}", "action_id": f"approve_{artifact}"},
                {"type": "button", "text": {"type": "plain_text", "text": f"❌ {artifact.upper()} 거절"},
                 "style": "danger", "value": f"reject|{req.job_id}|{artifact}", "action_id": f"reject_{artifact}"},
            ],
        })

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                json={"channel": f"#{channel}", "blocks": blocks, "text": "회의 초안 검토 요청"},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("error"))
            return data.get("ts", "")
    except Exception as exc:
        logger.warning("[Review] Failed to send Slack review: %s", exc)
        return ""


async def _update_slack_review(slack_ts: str, job_id: str) -> None:
    """Update the review message to show all decisions are done."""
    token = os.getenv("SLACK_BOT_TOKEN", "")
    channel = os.getenv("SLACK_REVIEW_CHANNEL", os.getenv("SLACK_BRIEF_CHANNEL", "general"))
    if not token or not slack_ts:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                "https://slack.com/api/chat.update",
                json={"channel": f"#{channel}", "ts": slack_ts,
                      "text": f"✅ 검토 완료 — job `{job_id}`",
                      "blocks": [{"type": "section", "text": {"type": "mrkdwn",
                                                               "text": f"✅ *검토 완료* — job `{job_id}` 처리 중입니다."}}]},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
    except Exception as exc:
        logger.warning("[Review] Failed to update Slack review message: %s", exc)


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def _load_draft(base_dir: Path, job, artifact: str) -> dict | None:
    """Find the draft JSON file for a given artifact.

    Storage uses _safe_name(meeting_id) as the directory — mirror that here.
    """
    safe_meeting_id = _safe_name(job.meeting_id)
    candidates = [
        base_dir / f"{safe_meeting_id}/{job.job_id}.{artifact}_drafts.json",
        base_dir / f"{safe_meeting_id}/{job.job_id}.{artifact}_draft.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    logger.warning("[Review] Draft file not found for %s:%s", job.job_id, artifact)
    return None
