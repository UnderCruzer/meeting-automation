"""
Thin wrapper that sends the Slack review message from the pipeline
without creating a circular import with app.routers.review.
"""
import logging
import os

import httpx

logger = logging.getLogger(__name__)


class SendReviewRequest:
    """Mirrors app.routers.review.SendReviewRequest — kept here to avoid circular import."""
    def __init__(self, job_id, meeting_id, file_key, routing, has_pii, summary_ko, quality_ok):
        self.job_id = job_id
        self.meeting_id = meeting_id
        self.file_key = file_key
        self.routing = routing
        self.has_pii = has_pii
        self.summary_ko = summary_ko
        self.quality_ok = quality_ok


async def send_review_message(req) -> str:
    """Send Slack review message and register job in approval store."""
    from app.services.approval_store import register_job

    register_job(req.job_id, req.meeting_id, req.routing)
    return await _post_slack_review(req)


async def _post_slack_review(req) -> str:
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
                                      "text": (f"*회의 ID:* `{req.meeting_id}`"
                                               f"{pii_warning}{quality_note}\n\n"
                                               f"{req.summary_ko[:300]}")}},
        {"type": "divider"},
    ]

    for artifact in req.routing:
        blocks.append({
            "type": "actions",
            "block_id": f"approval_{artifact}_{req.job_id}",
            "elements": [
                {"type": "button",
                 "text": {"type": "plain_text", "text": f"✅ {artifact.upper()} 승인"},
                 "style": "primary",
                 "value": f"approve|{req.job_id}|{artifact}",
                 "action_id": f"approve_{artifact}"},
                {"type": "button",
                 "text": {"type": "plain_text", "text": f"❌ {artifact.upper()} 거절"},
                 "style": "danger",
                 "value": f"reject|{req.job_id}|{artifact}",
                 "action_id": f"reject_{artifact}"},
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
