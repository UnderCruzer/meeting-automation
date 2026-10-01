"""Publish an approved meeting to Slack through the workflow's own stages.

Approval (#16) → Write Queue (#17) → Timezone Scheduler (#18) → Regional Slack Delivery (#19),
using the Slack Brief Draft (#14) format.
"""
from __future__ import annotations

import asyncio
import logging
import os

from app.models.summary import MeetingSummary
from app.services.draft_slack import generate_slack_draft
from app.services.timezone_scheduler import resolve_send_time
from app.services.write_queue import WriteTask, enqueue

logger = logging.getLogger(__name__)


def slack_enabled() -> bool:
    return bool(os.getenv("SLACK_BOT_TOKEN"))


def _timezones() -> list[str]:
    # Uploads carry no attendee timezones yet; the team's timezone(s) decide the region.
    raw = os.getenv("WORKSPACE_TIMEZONES") or os.getenv("DEFAULT_TIMEZONE", "Asia/Seoul")
    return [tz.strip() for tz in raw.split(",") if tz.strip()]


async def publish_job(workspace, audit, storage, job: dict, *, now: bool, requested_by: str | None) -> dict:
    """Queue the Slack brief for an approved job. Returns the publish state for the UI."""
    summary = MeetingSummary.model_validate(job["summary"])
    schedule = resolve_send_time(_timezones())
    if now:
        schedule.send_at, schedule.scheduled = None, False

    payload = {
        "title": job["title"],
        "text_ko": generate_slack_draft(summary, "ko").text,
        "text_en": generate_slack_draft(summary, "en").text,
        "schedule": {"region": schedule.region.value, "send_at": schedule.send_at,
                     "local_time": schedule.local_time, "scheduled": schedule.scheduled},
    }
    job_id = job["id"]
    # Write-queue audit lines go next to the job's files (its meeting folder).
    folder = next((path.parent.name for path in storage.base_dir.glob(f"*/{job_id}.*")), "workspace")

    async def still_wanted() -> bool:
        current = await asyncio.to_thread(workspace.get, job_id)
        return bool(current and current["status"] == "approved")

    async def on_result(ok: bool, detail) -> None:
        status = "sent" if ok else "failed"
        await asyncio.to_thread(
            workspace.set_publish, job_id, status,
            channel=(detail or {}).get("channel") if ok else None,
            error=None if ok else "Slack 게시에 실패했습니다. 토큰·채널·봇 초대를 확인하세요.",
        )
        await asyncio.to_thread(audit.record, "publish", "system", job_id=job_id, title=job["title"],
                                detail=f"slack {status} ({schedule.region.value})")

    state = "scheduled" if schedule.scheduled else "queued"
    await asyncio.to_thread(workspace.set_publish, job_id, state, at=schedule.send_at)
    await asyncio.to_thread(audit.record, "publish_request", requested_by, job_id=job_id, title=job["title"],
                            detail=f"{state} {schedule.local_time} ({schedule.region.value})")
    await enqueue(WriteTask(
        job_id=job_id, meeting_id=folder, artifact="regional_slack", payload=payload,
        base_dir=storage.base_dir, schedule_time=schedule.send_at or "",
        should_send=still_wanted, on_result=on_result,
    ))
    return {"publish_status": state, "publish_at": schedule.send_at, "local_time": schedule.local_time,
            "region": schedule.region.value}
