"""
Admin Alert service — sends Slack DM or channel message when a critical failure occurs.

Used by write_queue.py when all retries are exhausted.

Environment variables:
  SLACK_BOT_TOKEN      — required for sending
  SLACK_ADMIN_USER_ID  — Slack user ID for DM (e.g. U0123456789); falls back to channel
  SLACK_ALERT_CHANNEL  — fallback channel when SLACK_ADMIN_USER_ID is unset (default: general)
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)


async def send_failure_alert(
    job_id: str,
    artifact: str,
    meeting_id: str,
    error: str,
) -> None:
    """Notify admin of a Write Queue exhaustion event via Slack DM or channel.

    Silently logs and returns when SLACK_BOT_TOKEN is absent so that
    missing credentials do not cause secondary failures.
    """
    token = os.getenv("SLACK_BOT_TOKEN", "")
    if not token:
        logger.warning(
            "[Alert] SLACK_BOT_TOKEN not set — skipping failure alert for %s:%s",
            job_id, artifact,
        )
        return

    target = _resolve_target()
    text = _build_message(job_id, artifact, meeting_id, error)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                json={"channel": target, "text": text, "mrkdwn": True},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                logger.error("[Alert] Slack API error: %s", data.get("error"))
            else:
                logger.info("[Alert] Failure alert sent to %s", target)
    except Exception as exc:
        # Alert failure must never propagate — log and continue
        logger.error("[Alert] Failed to send alert: %s", exc)


def _resolve_target() -> str:
    """Return Slack DM target (user ID) or fallback channel."""
    admin_user = os.getenv("SLACK_ADMIN_USER_ID", "")
    if admin_user:
        return admin_user
    channel = os.getenv("SLACK_ALERT_CHANNEL", "general")
    return f"#{channel}"


def _build_message(job_id: str, artifact: str, meeting_id: str, error: str) -> str:
    return (
        f":rotating_light: *Write Queue — 최대 재시도 초과*\n"
        f"• *Job ID*: `{job_id}`\n"
        f"• *Artifact*: `{artifact}`\n"
        f"• *Meeting ID*: `{meeting_id}`\n"
        f"• *오류*: {error}\n\n"
        f"audit.jsonl을 확인하고 수동으로 재처리가 필요합니다."
    )
