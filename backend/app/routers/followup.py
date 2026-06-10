"""
Follow-up Automation endpoints — Issue #21

POST /followup/reminders   — D-1/D-day 리마인더 즉시 트리거 (cron용)
POST /followup/overdue     — 기한 초과 알림 트리거
POST /followup/jira        — Jira webhook 수신 (issue:updated)
"""
import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
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
async def jira_webhook(
    request: Request,
    payload: JiraWebhookPayload,
    x_hub_signature: str = Header(default=""),
):
    """Jira issue:updated webhook — 상태 변경 시 이해관계자 알림.

    If JIRA_WEBHOOK_SECRET is set, verifies the X-Hub-Signature header
    (HMAC-SHA256 of the raw body) sent by Jira Connect / webhook secret.
    Requests without a valid signature are rejected with 401.
    """
    secret = os.getenv("JIRA_WEBHOOK_SECRET", "")
    if secret:
        raw_body = await request.body()
        expected = "sha256=" + hmac.new(
            secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected, x_hub_signature):
            logger.warning("[Followup] Jira webhook signature mismatch — rejected")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    result = await handle_jira_webhook(payload.model_dump())
    return result
