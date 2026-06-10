"""
Follow-up Automation — Issue #21

- Action Item 기한 리마인더 (D-1, D-day)
- Jira 상태 변경 webhook 처리
- 미완료 항목 이해관계자 Slack 알림
- 다음 회의 Agenda 후보 자동 생성 (digest.send_meeting_agenda 위임)
"""
from __future__ import annotations

import logging
import os
from base64 import b64encode
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import json

import httpx

logger = logging.getLogger(__name__)

_STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "./data/recordings"))


# ── Action Item 리마인더 ───────────────────────────────────────────────────────

def _load_action_items() -> list[dict]:
    """analysis JSON에서 due_date가 있는 action_item 수집."""
    items = []
    if not _STORAGE_DIR.exists():
        return items
    for path in _STORAGE_DIR.rglob("*.analysis.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data.get("action_items", []):
                # action_item이 dict이면 due_date 필드 사용, str이면 스킵
                if isinstance(item, dict) and item.get("due_date"):
                    item["_source"] = str(path)
                    items.append(item)
        except Exception as exc:
            logger.warning("[Followup] Failed to load %s: %s", path, exc)
    return items


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


async def send_action_item_reminders() -> int:
    """
    D-1 / D-day 리마인더를 담당자 Slack DM으로 발송.
    Returns: 발송된 리마인더 수
    """
    today = date.today()
    tomorrow = today + timedelta(days=1)
    sent = 0

    for item in _load_action_items():
        try:
            due = date.fromisoformat(str(item["due_date"]))
        except (ValueError, TypeError):
            continue

        if due not in (today, tomorrow):
            continue

        label = "🔴 *오늘 마감*" if due == today else "🟡 *내일 마감*"
        assignee_id = item.get("assignee_slack_id") or item.get("assignee", "")
        if not assignee_id:
            continue

        text = (
            f"{label} — 액션 아이템 리마인더\n\n"
            f"*내용:* {item.get('description', item.get('text', ''))}\n"
            f"*마감일:* {due.isoformat()}\n"
            f"_해당 항목을 Jira에서 완료 처리해주세요._"
        )
        await _notify_slack(assignee_id, text)
        sent += 1

    logger.info("[Followup] Action item reminders sent: %d", sent)
    return sent


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


# ── 미완료 항목 알림 ──────────────────────────────────────────────────────────

async def notify_overdue_items() -> int:
    """기한 초과 Action Item을 담당자에게 알림. Returns: 발송 수"""
    today = date.today()
    sent = 0

    for item in _load_action_items():
        try:
            due = date.fromisoformat(str(item["due_date"]))
        except (ValueError, TypeError):
            continue

        if due >= today:
            continue   # 아직 기한 내

        assignee_id = item.get("assignee_slack_id") or item.get("assignee", "")
        if not assignee_id:
            continue

        overdue_days = (today - due).days
        text = (
            f"⚠️ *기한 초과 — {overdue_days}일 경과*\n\n"
            f"*내용:* {item.get('description', item.get('text', ''))}\n"
            f"*원래 마감일:* {due.isoformat()}\n"
            f"_빠른 처리 또는 기한 재조정을 요청드립니다._"
        )
        await _notify_slack(assignee_id, text)
        sent += 1

    logger.info("[Followup] Overdue item notifications sent: %d", sent)
    return sent
