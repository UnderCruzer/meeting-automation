"""
Follow-up Automation — Issue #21

- Jira 상태 변경 webhook 처리 → 이해관계자 Slack 알림

Due/overdue reminders for action items moved to services/briefing.py (#83): approved meetings
only, with completion tracking and free-text due dates.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)


# ── Action Item 리마인더 ───────────────────────────────────────────────────────

async def _notify_slack(user_id: str, text: str) -> None:
    token = os.getenv("SLACK_BOT_TOKEN", "")
    if not token:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                json={"channel": user_id, "text": text, "mrkdwn": True},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("error"))
    except Exception as exc:
        logger.warning("[Followup] Slack notify failed for %s: %s", user_id, exc)


# ── Jira webhook 처리 ─────────────────────────────────────────────────────────

async def handle_jira_webhook(payload: dict) -> dict:
    """
    Jira issue:updated webhook 처리.
    상태가 Done/Closed로 변경 시 이해관계자에게 Slack 알림.
    Returns: {"notified": int}
    """
    issue = payload.get("issue", {})
    changelog = payload.get("changelog", {})
    issue_key = issue.get("key", "")
    if not issue_key:
        logger.warning("[Followup] Jira webhook missing issue.key — ignoring")
        return {"notified": 0}
    issue_summary = issue.get("fields", {}).get("summary", "")

    # 상태 변경 항목 찾기
    status_change = next(
        (item for item in changelog.get("items", []) if item.get("field") == "status"),
        None,
    )
    if not status_change:
        return {"notified": 0}

    new_status = status_change.get("toString", "").lower()
    done_statuses = {"done", "closed", "resolved", "완료"}
    if new_status not in done_statuses:
        return {"notified": 0}

    # 이해관계자 조회 (env: JIRA_STAKEHOLDER_SLACK_IDS — comma-separated)
    stakeholders = [
        s.strip()
        for s in os.getenv("JIRA_STAKEHOLDER_SLACK_IDS", "").split(",")
        if s.strip()
    ]
    if not stakeholders:
        logger.info("[Followup] No stakeholders configured for Jira webhook")
        return {"notified": 0}

    text = (
        f"✅ *Jira 이슈 완료* — `{issue_key}`\n\n"
        f"*제목:* {issue_summary}\n"
        f"*상태:* {status_change.get('fromString')} → {status_change.get('toString')}"
    )

    notified = 0
    for user_id in stakeholders:
        await _notify_slack(user_id, text)
        notified += 1

    logger.info("[Followup] Jira webhook: %s → %s, notified %d stakeholders", issue_key, new_status, notified)
    return {"notified": notified}
