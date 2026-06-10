"""
Follow-up Automation endpoints — Issue #21

POST /followup/reminders   — D-1/D-day 리마인더 즉시 트리거 (cron용)
POST /followup/overdue     — 기한 초과 알림 트리거
POST /followup/jira        — Jira webhook 수신 (issue:updated)
"""
import logging

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from app.services.followup import (
    handle_jira_webhook,
    notify_overdue_items,
    send_action_item_reminders,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/followup")


class JiraWebhookPayload(BaseModel):
    issue: dict = {}
    changelog: dict = {}
    webhookEvent: str = ""


@router.post("/reminders")
async def trigger_reminders(background_tasks: BackgroundTasks):
    background_tasks.add_task(send_action_item_reminders)
    return {"triggered": "action_item_reminders"}


@router.post("/overdue")
async def trigger_overdue(background_tasks: BackgroundTasks):
    background_tasks.add_task(notify_overdue_items)
    return {"triggered": "overdue_notifications"}


@router.post("/jira")
async def jira_webhook(payload: JiraWebhookPayload):
    """Jira issue:updated webhook — 상태 변경 시 이해관계자 알림."""
    result = await handle_jira_webhook(payload.model_dump())
    return result
