"""
Regional Slack Delivery — Issue #19

NA / EU / APAC 채널 라우팅, KR/EN 자동 언어 선택,
스레드 답글 vs 새 메시지 분기.

Usage:
    schedule = resolve_send_time(timezones)
    await deliver_regional(summary, schedule, thread_ts=existing_ts)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

from app.services.timezone_scheduler import Region, SendSchedule

logger = logging.getLogger(__name__)

# ── Channel mapping (overridable via env) ────────────────────────────────────

def _channel(region: Region) -> str:
    env_map = {
        Region.APAC:    "SLACK_CHANNEL_APAC",
        Region.EU:      "SLACK_CHANNEL_EU",
        Region.NA:      "SLACK_CHANNEL_NA",
        Region.UNKNOWN: "SLACK_CHANNEL_APAC",
    }
    default_map = {
        Region.APAC:    "meeting-brief-apac",
        Region.EU:      "meeting-brief-eu",
        Region.NA:      "meeting-brief-na",
        Region.UNKNOWN: "meeting-brief-apac",
    }
    return os.getenv(env_map[region], default_map[region])


# ── Language selection ────────────────────────────────────────────────────────

def _select_language(region: Region) -> str:
    """Return 'ko' for APAC, 'en' for NA/EU/UNKNOWN."""
    return "ko" if region == Region.APAC else "en"


# ── Message builder ───────────────────────────────────────────────────────────

@dataclass
class RegionalMessage:
    channel: str
    text: str
    lang: str
    region: Region
    thread_ts: str | None   # None = new message; str = reply in thread


def build_regional_message(
    summary_ko: str,
    summary_en: str,
    meeting_id: str,
    schedule: SendSchedule,
    thread_ts: str | None = None,
) -> RegionalMessage:
    """Build a localised Slack mrkdwn message for the given region."""
    region = schedule.region
    lang = _select_language(region)
    channel = _channel(region)

    if lang == "ko":
        header = f"📋 *회의 요약* | `{meeting_id}`"
        body = summary_ko
        footer = f"_지역: {region.value} · {schedule.local_time}_"
    else:
        header = f"📋 *Meeting Brief* | `{meeting_id}`"
        body = summary_en
        footer = f"_Region: {region.value} · {schedule.local_time}_"

    text = f"{header}\n\n{body}\n\n{footer}"
    return RegionalMessage(
        channel=channel,
        text=text,
        lang=lang,
        region=region,
        thread_ts=thread_ts,
    )


# ── Slack delivery ────────────────────────────────────────────────────────────

async def deliver_regional(
    summary_ko: str,
    summary_en: str,
    meeting_id: str,
    schedule: SendSchedule,
    thread_ts: str | None = None,
) -> dict:
    """
    Post a regional Slack message.

    If schedule.scheduled is True, the message text is still sent immediately
    (caller is responsible for honouring send_at via write_queue schedule_time).
    Returns {"ok": bool, "ts": str, "channel": str}.
    """
    token = os.getenv("SLACK_BOT_TOKEN", "")
    if not token:
        logger.warning("[Regional] SLACK_BOT_TOKEN not set — skipping")
        return {"ok": False, "error": "no_token"}

    msg = build_regional_message(summary_ko, summary_en, meeting_id, schedule, thread_ts)

    payload: dict = {
        "channel": f"#{msg.channel}",
        "text": msg.text,
        "mrkdwn": True,
    }
    if msg.thread_ts:
        payload["thread_ts"] = msg.thread_ts
        payload["reply_broadcast"] = False   # thread reply only; set True to also post to channel

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("error", "slack_error"))

            logger.info(
                "[Regional] Delivered to #%s (lang=%s, region=%s, thread=%s)",
                msg.channel, msg.lang, msg.region.value, msg.thread_ts,
            )
            return {"ok": True, "ts": data.get("ts", ""), "channel": data.get("channel", "")}

    except Exception as exc:
        logger.warning("[Regional] Delivery failed for %s: %s", meeting_id, exc)
        return {"ok": False, "error": str(exc)}
