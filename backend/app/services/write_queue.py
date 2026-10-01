"""
Write Queue — asyncio.Queue workers that publish approved drafts.

Workers: jira_worker, confluence_worker, slack_worker, pdf_worker, regional_slack
Each retries up to 3 times with exponential backoff on failure.
Tasks whose schedule_time is a future ISO timestamp wait until then (Timezone Scheduler, #18).
Scheduled tasks live in memory: a restart drops them (callers mark them failed on recovery).
Audit log written to data/recordings/<job_id>/audit.log.
"""
import asyncio
import json
import logging
import os
from base64 import b64encode
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import httpx

logger = logging.getLogger(__name__)

_queue: asyncio.Queue = asyncio.Queue()
_MAX_RETRIES = 3


@dataclass
class WriteTask:
    job_id: str
    meeting_id: str      # needed for audit log path (mirrors draft file layout)
    artifact: str        # "jira" | "confluence" | "slack"
    payload: dict        # draft content
    base_dir: Path
    schedule_time: str = ""
    # Optional hooks: skip at send time (e.g. meeting deleted) / report the final outcome.
    should_send: Optional[Callable[[], Awaitable[bool]]] = None
    on_result: Optional[Callable[[bool, Any], Awaitable[None]]] = None


_delayed: set[asyncio.Task] = set()


def _delay_seconds(schedule_time: str, now: Optional[datetime] = None) -> float:
    """Seconds until schedule_time (ISO 8601); 0 for empty, past or non-timestamp values."""
    try:
        when = datetime.fromisoformat(schedule_time)
    except ValueError:
        return 0.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - (now or datetime.now(timezone.utc))).total_seconds())


async def enqueue(task: WriteTask) -> None:
    delay = _delay_seconds(task.schedule_time)
    if delay > 0:
        async def release() -> None:
            await asyncio.sleep(delay)
            await _queue.put(task)
        pending = asyncio.create_task(release())
        _delayed.add(pending)
        pending.add_done_callback(_delayed.discard)
        logger.info("[WriteQueue] Scheduled %s:%s in %.0fs", task.job_id, task.artifact, delay)
        return
    await _queue.put(task)
    logger.info("[WriteQueue] Enqueued %s:%s", task.job_id, task.artifact)


async def start_worker() -> None:
    """Run forever — call once at app startup via asyncio.create_task."""
    logger.info("[WriteQueue] Worker started")
    while True:
        task: WriteTask = await _queue.get()
        try:
            await _dispatch(task)
        except Exception:
            logger.exception("[WriteQueue] Unhandled error for %s:%s", task.job_id, task.artifact)
        finally:
            _queue.task_done()


async def _dispatch(task: WriteTask) -> None:
    # Honour cancellation from timezone_scheduler.cancel_scheduled()
    if task.schedule_time == "cancelled" or (task.should_send and not await task.should_send()):
        logger.info("[WriteQueue] Skipping cancelled task %s:%s", task.job_id, task.artifact)
        await _write_audit(task, success=False, detail={"error": "cancelled"})
        return

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            if task.artifact == "jira":
                result = await _publish_jira(task.payload)
            elif task.artifact == "confluence":
                result = await _publish_confluence(task.payload)
            elif task.artifact == "slack":
                result = await _publish_slack(task.payload)
            elif task.artifact == "pdf":
                result = await _publish_pdf_slack(task.payload, task.base_dir)
            elif task.artifact == "regional_slack":
                result = await _publish_regional_slack(task.payload)
            else:
                logger.warning("[WriteQueue] Unknown artifact type: %s", task.artifact)
                return

            await _write_audit(task, success=True, detail=result)
            logger.info("[WriteQueue] ✓ %s:%s published", task.job_id, task.artifact)
            if task.on_result:
                await task.on_result(True, result)
            return
        except Exception as exc:
            logger.warning("[WriteQueue] Attempt %d/%d failed for %s:%s — %s",
                           attempt, _MAX_RETRIES, task.job_id, task.artifact, exc)
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(2 ** (attempt - 1))

    await _write_audit(task, success=False, detail={"error": "max retries exceeded"})
    logger.error("[WriteQueue] ✗ %s:%s failed after %d attempts", task.job_id, task.artifact, _MAX_RETRIES)
    if task.on_result:
        await task.on_result(False, {"error": "max retries exceeded"})

    from app.services.alert import send_failure_alert
    await send_failure_alert(
        job_id=task.job_id,
        artifact=task.artifact,
        meeting_id=task.meeting_id,
        error="max retries exceeded",
    )


async def _publish_jira(payload: dict) -> dict:
    base_url = os.getenv("JIRA_BASE_URL", "").rstrip("/")
    project = os.getenv("JIRA_PROJECT_KEY", "")
    token = os.getenv("JIRA_API_TOKEN", "")
    email = os.getenv("JIRA_EMAIL", "")
    if not all([base_url, project, token, email]):
        raise RuntimeError("Jira credentials not configured")

    auth = b64encode(f"{email}:{token}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}
    results = []

    async with httpx.AsyncClient(timeout=30) as client:
        for draft in payload.get("drafts", []):
            if draft["action"] == "create":
                body = {
                    "fields": {
                        "project": {"key": project},
                        "summary": draft["summary"],
                        "description": {"type": "doc", "version": 1,
                                        "content": [{"type": "paragraph", "content":
                                                     [{"type": "text", "text": draft["description"]}]}]},
                        "issuetype": {"name": draft.get("issue_type", "Task")},
                        "priority": {"name": draft.get("priority", "Medium")},
                    }
                }
                resp = await client.post(f"{base_url}/rest/api/3/issue", json=body, headers=headers)
                resp.raise_for_status()
                results.append({"action": "created", "key": resp.json().get("key")})
            elif draft["action"] == "comment" and draft.get("existing_key"):
                body = {"body": {"type": "doc", "version": 1,
                                 "content": [{"type": "paragraph", "content":
                                              [{"type": "text", "text": draft["description"]}]}]}}
                resp = await client.post(
                    f"{base_url}/rest/api/3/issue/{draft['existing_key']}/comment",
                    json=body, headers=headers,
                )
                resp.raise_for_status()
                results.append({"action": "commented", "key": draft["existing_key"]})

    return {"results": results}


async def _publish_confluence(payload: dict) -> dict:
    base_url = os.getenv("CONFLUENCE_BASE_URL", "").rstrip("/")
    token = os.getenv("CONFLUENCE_API_TOKEN", "")
    email = os.getenv("CONFLUENCE_EMAIL", "")
    if not all([base_url, token, email]):
        raise RuntimeError("Confluence credentials not configured")

    space_key = payload.get("space_key") or os.getenv("CONFLUENCE_SPACE_KEY", "")
    if not space_key:
        raise RuntimeError("Confluence space_key not configured")

    auth = b64encode(f"{email}:{token}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}
    body = {
        "type": "page",
        "title": payload["title"],
        "space": {"key": space_key},
        "body": {"storage": {"value": payload["body"], "representation": "storage"}},
    }
    if payload.get("parent_page_id"):
        body["ancestors"] = [{"id": payload["parent_page_id"]}]

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{base_url}/wiki/rest/api/content", json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    return {"page_id": data.get("id"), "url": f"{base_url}{data.get('_links', {}).get('webui', '')}"}


async def _publish_slack(payload: dict) -> dict:
    token = os.getenv("SLACK_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN not configured")

    channel = payload.get("suggested_channel", os.getenv("SLACK_BRIEF_CHANNEL", "general"))
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://slack.com/api/chat.postMessage",
            json={"channel": channel, "text": payload["text"], "mrkdwn": True},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("error", "Slack API error"))

    return {"ts": data.get("ts"), "channel": data.get("channel")}


async def _publish_regional_slack(payload: dict) -> dict:
    """Regional Slack Delivery (#19): region channel + KR/EN text chosen by the schedule's region."""
    from app.services.regional_delivery import deliver_regional
    from app.services.timezone_scheduler import Region, SendSchedule

    sched = payload["schedule"]
    schedule = SendSchedule(region=Region(sched["region"]), send_at=sched.get("send_at"),
                            local_time=sched.get("local_time", ""), scheduled=bool(sched.get("scheduled")))
    result = await deliver_regional(payload["text_ko"], payload["text_en"], payload["title"], schedule)
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "slack delivery failed"))
    return result


async def _publish_pdf_slack(payload: dict, base_dir: Path) -> dict:
    """Generate a PDF from OrchestratorOutput and upload it to Slack as a file.

    If SLACK_BOT_TOKEN is absent, skips upload and returns the local path only.
    """
    from app.models.analysis import OrchestratorOutput
    from app.services.pdf_report import save_pdf

    output = OrchestratorOutput(**payload["output"])
    lang = payload.get("lang", "en")
    channel = payload.get("channel", os.getenv("SLACK_BRIEF_CHANNEL", "general"))

    pdf_path = save_pdf(output, base_dir=base_dir, lang=lang)
    result: dict = {"local_path": str(pdf_path)}

    token = os.getenv("SLACK_BOT_TOKEN", "")
    if not token:
        logger.warning("[WriteQueue] SLACK_BOT_TOKEN not set — PDF saved locally only: %s", pdf_path)
        return result

    async with httpx.AsyncClient(timeout=60) as client:
        with open(pdf_path, "rb") as f:
            resp = await client.post(
                "https://slack.com/api/files.uploadV2",
                headers={"Authorization": f"Bearer {token}"},
                data={
                    "channels": channel,
                    "filename": pdf_path.name,
                    "title": f"Meeting Report — {output.meeting_id}",
                    "initial_comment": payload.get(
                        "initial_comment",
                        f":page_facing_up: Meeting minutes attached for `{output.meeting_id}`",
                    ),
                },
                files={"file": (pdf_path.name, f, "application/pdf")},
            )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("error", "Slack files.uploadV2 error"))

    result["slack_file_id"] = data.get("file", {}).get("id")
    result["channel"] = channel
    logger.info("[WriteQueue] PDF uploaded to Slack #%s — file_id=%s", channel, result["slack_file_id"])
    return result


async def _write_audit(task: WriteTask, success: bool, detail: Any) -> None:
    # fix: was task.job_id[:8] — unrelated dir; use meeting_id subdir to match draft file layout
    audit_path = task.base_dir / task.meeting_id / "audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "job_id": task.job_id,
        "artifact": task.artifact,
        "success": success,
        "detail": detail,
    }
    # Append-only — use sync write since audit is non-critical path
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
