"""
Write Queue — asyncio.Queue workers that publish approved drafts.

Workers: jira_worker, confluence_worker, slack_worker
Each retries up to 3 times with exponential backoff on failure.
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
from typing import Any

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


async def enqueue(task: WriteTask) -> None:
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
    if task.schedule_time == "cancelled":
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
            else:
                logger.warning("[WriteQueue] Unknown artifact type: %s", task.artifact)
                return

            await _write_audit(task, success=True, detail=result)
            logger.info("[WriteQueue] ✓ %s:%s published", task.job_id, task.artifact)
            return
        except Exception as exc:
            logger.warning("[WriteQueue] Attempt %d/%d failed for %s:%s — %s",
                           attempt, _MAX_RETRIES, task.job_id, task.artifact, exc)
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(2 ** (attempt - 1))

    await _write_audit(task, success=False, detail={"error": "max retries exceeded"})
    logger.error("[WriteQueue] ✗ %s:%s failed after %d attempts", task.job_id, task.artifact, _MAX_RETRIES)


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

    auth = b64encode(f"{email}:{token}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}
    body = {
        "type": "page",
        "title": payload["title"],
        "space": {"key": payload["space_key"]},
        "body": {"storage": {"value": payload["body"], "representation": "storage"}},
    }
    if payload.get("parent_page_id"):
        body["ancestors"] = [{"id": payload["parent_page_id"]}]

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{base_url}/rest/api/content", json=body, headers=headers)
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
            json={"channel": f"#{channel}", "text": payload["text"], "mrkdwn": True},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("error", "Slack API error"))

    return {"ts": data.get("ts"), "channel": data.get("channel")}


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
