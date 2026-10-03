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

    result: Any = None
    last_error = "unknown"
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
            break
        except Exception as exc:
            last_error = str(exc) or type(exc).__name__
            logger.warning("[WriteQueue] Attempt %d/%d failed for %s:%s — %s",
                           attempt, _MAX_RETRIES, task.job_id, task.artifact, exc)
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(2 ** (attempt - 1))
    else:
        await _write_audit(task, success=False, detail={"error": "max retries exceeded"})
        logger.error("[WriteQueue] ✗ %s:%s failed after %d attempts", task.job_id, task.artifact, _MAX_RETRIES)
        await _report(task, False, {"error": last_error})

        from app.services.alert import send_failure_alert
        await send_failure_alert(
            job_id=task.job_id,
            artifact=task.artifact,
            meeting_id=task.meeting_id,
            error="max retries exceeded",
        )
        return

    # Published. Bookkeeping below must never trigger a re-publish (duplicate message).
    logger.info("[WriteQueue] ✓ %s:%s published", task.job_id, task.artifact)
    try:
        await _write_audit(task, success=True, detail=result)
    except Exception:
        logger.exception("[WriteQueue] Audit write failed for %s:%s", task.job_id, task.artifact)
    await _report(task, True, result)


async def _report(task: WriteTask, ok: bool, detail: Any) -> None:
    if not task.on_result:
        return
    try:
        await task.on_result(ok, detail)
    except Exception:
        logger.exception("[WriteQueue] Result hook failed for %s:%s", task.job_id, task.artifact)


async def _publish_jira(payload: dict) -> dict:
    """Create issues / add comments for the approved drafts (workflow 12).

    Each finished draft records its result in the payload, so a retry after a partial failure
    continues with the rest instead of creating the same issues again.
    """
    from app.services import atlassian

    site = atlassian.jira_site()
    if site is None:
        raise RuntimeError("Jira not configured")

    async with httpx.AsyncClient(timeout=30) as client:
        for draft in payload.get("drafts", []):
            if draft.get("result"):
                continue
            if draft["action"] == "comment":
                if not atlassian.valid_issue_key(draft.get("existing_key", ""), site.scope):
                    raise RuntimeError(f"issue {draft.get('existing_key')!r} is outside project {site.scope}")
                resp = await client.post(
                    f"{site.base_url}/rest/api/3/issue/{draft['existing_key']}/comment",
                    json={"body": atlassian.to_adf(draft["description"])}, headers=site.headers(),
                )
                if resp.is_error:
                    raise RuntimeError(f"Jira comment failed: {atlassian.error_message(resp)}")
                draft["result"] = {"action": "commented", "key": draft["existing_key"],
                                   "url": f"{site.base_url}/browse/{draft['existing_key']}"}
                continue

            fields = {
                "project": {"key": site.scope},
                "summary": draft["summary"][:250],
                "description": atlassian.to_adf(draft["description"]),
                "issuetype": {"name": atlassian.jira_issue_type()},
                "priority": {"name": draft.get("priority") or "Medium"},
                "labels": [atlassian.LABEL],
            }
            resp = await client.post(f"{site.base_url}/rest/api/3/issue", json={"fields": fields},
                                     headers=site.headers())
            rejected = atlassian.error_fields(resp) & set(atlassian.OPTIONAL_JIRA_FIELDS) if resp.status_code == 400 else set()
            if rejected:
                # e.g. team-managed projects without a priority field — create without them.
                for name in rejected:
                    fields.pop(name, None)
                resp = await client.post(f"{site.base_url}/rest/api/3/issue", json={"fields": fields},
                                         headers=site.headers())
            if resp.is_error:
                raise RuntimeError(f"Jira create failed: {atlassian.error_message(resp)}")
            key = resp.json().get("key")
            draft["result"] = {"action": "created", "key": key, "url": f"{site.base_url}/browse/{key}"}

    return {"results": [d["result"] for d in payload.get("drafts", []) if d.get("result")]}


async def _publish_confluence(payload: dict) -> dict:
    """Create the meeting-minutes page in the configured space (workflow 13, Confluence v2 API)."""
    from app.services import atlassian

    if payload.get("result"):
        return payload["result"]
    site = atlassian.confluence_site()
    if site is None:
        raise RuntimeError("Confluence not configured")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{site.base_url}/wiki/api/v2/spaces", params={"keys": site.scope},
                                headers=site.headers())
        spaces = resp.json().get("results", []) if resp.is_success else []
        if not spaces:
            raise RuntimeError(f"Confluence space {site.scope} not found ({atlassian.error_message(resp)})")

        titles = [payload["title"], f"{payload['title']} ({payload.get('suffix') or 'meeting'})"]
        for title in titles:
            body = {"spaceId": spaces[0]["id"], "status": "current", "title": title[:255],
                    "body": {"representation": "storage", "value": payload["body"]}}
            if payload.get("parent_page_id"):
                body["parentId"] = payload["parent_page_id"]
            resp = await client.post(f"{site.base_url}/wiki/api/v2/pages", json=body, headers=site.headers())
            # Page titles are unique per space: a same-titled meeting gets the suffixed title.
            if resp.status_code == 400 and "title" in atlassian.error_message(resp).lower() and title != titles[-1]:
                continue
            break
        if resp.is_error:
            raise RuntimeError(f"Confluence create failed: {atlassian.error_message(resp)}")
        data = resp.json()

    links = data.get("_links") or {}
    payload["result"] = {"page_id": data.get("id"), "title": data.get("title"),
                         "url": f"{links.get('base') or site.base_url + '/wiki'}{links.get('webui', '')}"}
    return payload["result"]


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
