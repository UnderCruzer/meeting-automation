"""
Meeting Agenda suggestions — Issue #20.

Morning Brief / Daily / Weekly Digest moved to services/briefing.py (#83): they now use only
approved meetings and a fixed template instead of LLM summaries of unreviewed analyses.
"""
from __future__ import annotations

import logging
import os

import httpx

from app.services import llm

logger = logging.getLogger(__name__)


# ── Slack poster ──────────────────────────────────────────────────────────────

async def _post_to_slack(channel: str, text: str) -> bool:
    token = os.getenv("SLACK_BOT_TOKEN", "")
    if not token:
        logger.warning("[Digest] SLACK_BOT_TOKEN not set")
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                json={"channel": channel, "text": text, "mrkdwn": True},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("error"))
            return True
    except Exception as exc:
        logger.warning("[Digest] Slack post failed: %s", exc)
        return False


async def send_meeting_agenda(upcoming_summaries: list[str], lang: str = "ko") -> None:
    """
    Meeting Agenda — 다가오는 회의 전 어젠다 후보 생성.
    upcoming_summaries: 이전 관련 회의 요약 텍스트 목록
    """
    if not upcoming_summaries:
        return

    joined = "\n".join(f"- {s}" for s in upcoming_summaries[:5])
    prompt = (
        f"다음 관련 회의 요약을 참고해서 오늘 회의 어젠다 후보를 3–5개 제안해줘:\n{joined}"
        if lang == "ko" else
        f"Based on these related meeting summaries, suggest 3–5 agenda items:\n{joined}"
    )

    try:
        text = await llm.generate_text(prompt=prompt, max_tokens=512)
    except Exception as exc:
        logger.warning("[Digest] Agenda generation failed: %s", exc)
        return

    header = "📋 *회의 어젠다 후보*" if lang == "ko" else "📋 *Suggested Meeting Agenda*"
    channel = os.getenv("DIGEST_CHANNEL", os.getenv("SLACK_BRIEF_CHANNEL", "general"))
    await _post_to_slack(channel, f"{header}\n\n{text}")  # channel IDs break with a "#" prefix
