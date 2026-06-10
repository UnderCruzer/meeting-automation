"""
Brief / Digest Automation — Issue #20

Morning Brief (daily), Daily Digest, Weekly Digest, Meeting Agenda 생성.
Claude API로 요약 생성 후 Slack 발송.

Scheduler entry points (call from a cron job or APScheduler):
    await send_morning_brief()
    await send_daily_digest()
    await send_weekly_digest()
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import anthropic
import httpx

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"
_STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "./data/recordings"))


# ── Subscriber management (MVP: env var list) ─────────────────────────────────

def _subscribers() -> list[str]:
    """Return list of Slack user IDs from env (comma-separated)."""
    raw = os.getenv("DIGEST_SUBSCRIBERS", "")
    return [u.strip() for u in raw.split(",") if u.strip()]


# ── Transcript loader ─────────────────────────────────────────────────────────

def _load_transcripts_since(since: datetime) -> list[dict]:
    """Load all analysis JSON files created after `since` (UTC)."""
    results = []
    if not _STORAGE_DIR.exists():
        return results
    for path in sorted(_STORAGE_DIR.rglob("*.analysis.json")):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if mtime < since:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            results.append(data)
        except Exception as exc:
            logger.warning("[Digest] Failed to load %s: %s", path, exc)
    return results


# ── Claude summariser ─────────────────────────────────────────────────────────

async def _generate_digest_text(
    analyses: list[dict],
    digest_type: str,   # "morning_brief" | "daily" | "weekly"
    lang: str = "ko",
) -> str:
    """Ask Claude to generate a digest from a list of analysis dicts."""
    if not analyses:
        return "📭 기간 내 회의 기록이 없습니다." if lang == "ko" else "📭 No meetings found in this period."

    def _safe_join(val: object) -> str:
        """join list[str]; stringify if scalar (Claude occasionally returns str instead of list)."""
        if isinstance(val, list):
            return ", ".join(str(v) for v in val[:3])
        return str(val)[:120] if val else ""

    summary_blocks = []
    for i, a in enumerate(analyses[:20], 1):   # cap at 20 meetings
        summary_blocks.append(
            f"[{i}] summary: {a.get('summary_ko' if lang == 'ko' else 'summary_en', '')}\n"
            f"    decisions: {_safe_join(a.get('decisions', []))}\n"
            f"    action_items: {_safe_join(a.get('action_items', []))}"
        )
    meetings_text = "\n".join(summary_blocks)

    type_instructions = {
        "morning_brief": (
            "오늘의 예정 사항과 어제 결정사항 핵심만 3–5 bullet으로 정리해줘. "
            "간결하고 실행 가능한 내용 위주로."
        ) if lang == "ko" else (
            "Summarise yesterday's key decisions and today's agenda in 3–5 bullets. "
            "Keep it concise and actionable."
        ),
        "daily": (
            "오늘 회의 전체를 주제별로 묶어 Daily Digest를 작성해줘. "
            "주요 결정, 액션 아이템, 다음 단계를 포함해."
        ) if lang == "ko" else (
            "Write a Daily Digest grouping today's meetings by topic. "
            "Include key decisions, action items, and next steps."
        ),
        "weekly": (
            "이번 주 회의 트렌드와 반복 주제, 미완료 액션 아이템을 포함한 Weekly Digest를 작성해줘."
        ) if lang == "ko" else (
            "Write a Weekly Digest including this week's recurring themes, "
            "trends, and outstanding action items."
        ),
    }
    instruction = type_instructions.get(digest_type, type_instructions["daily"])

    prompt = (
        f"다음은 최근 회의 분석 결과입니다:\n\n{meetings_text}\n\n"
        f"{instruction}\n\n"
        f"Slack mrkdwn 형식으로 작성하고, 헤더(*)와 bullet(•)을 사용해."
    ) if lang == "ko" else (
        f"Here are recent meeting analyses:\n\n{meetings_text}\n\n"
        f"{instruction}\n\n"
        f"Format as Slack mrkdwn with headers (*) and bullets (•)."
    )

    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", "")).messages.create(
                model=_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            ),
        )
        return response.content[0].text
    except Exception as exc:
        logger.warning("[Digest] Claude call failed: %s", exc)
        return f"⚠️ 다이제스트 생성 실패: {exc}"


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


async def _dm_subscribers(text: str) -> None:
    """Send DM to all subscribed users."""
    for user_id in _subscribers():
        await _post_to_slack(user_id, text)


# ── Public scheduler entry points ─────────────────────────────────────────────

async def send_morning_brief(lang: str = "ko") -> None:
    """
    Morning Brief — 매일 오전 발송.
    어제 회의 결정사항 + 오늘 예정 요약.
    """
    since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0) - timedelta(days=1)
    analyses = _load_transcripts_since(since)
    text = await _generate_digest_text(analyses, "morning_brief", lang)

    header = "☀️ *Morning Brief*" if lang == "ko" else "☀️ *Morning Brief*"
    channel = os.getenv("DIGEST_CHANNEL", os.getenv("SLACK_BRIEF_CHANNEL", "general"))

    await _post_to_slack(f"#{channel}", f"{header}\n\n{text}")
    await _dm_subscribers(f"{header}\n\n{text}")
    logger.info("[Digest] Morning brief sent (%d meetings)", len(analyses))


async def send_daily_digest(lang: str = "ko") -> None:
    """
    Daily Digest — 당일 회의 전체 요약 (오후 발송).
    """
    since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
    analyses = _load_transcripts_since(since)
    text = await _generate_digest_text(analyses, "daily", lang)

    header = "📅 *Daily Digest*"
    channel = os.getenv("DIGEST_CHANNEL", os.getenv("SLACK_BRIEF_CHANNEL", "general"))

    await _post_to_slack(f"#{channel}", f"{header}\n\n{text}")
    await _dm_subscribers(f"{header}\n\n{text}")
    logger.info("[Digest] Daily digest sent (%d meetings)", len(analyses))


async def send_weekly_digest(lang: str = "ko") -> None:
    """
    Weekly Digest — 주간 트렌드 + 미완료 액션 아이템 (금요일 오후 발송).
    """
    since = datetime.now(timezone.utc) - timedelta(days=7)
    analyses = _load_transcripts_since(since)
    text = await _generate_digest_text(analyses, "weekly", lang)

    header = "📊 *Weekly Digest*" if lang == "ko" else "📊 *Weekly Digest*"
    channel = os.getenv("DIGEST_CHANNEL", os.getenv("SLACK_BRIEF_CHANNEL", "general"))

    await _post_to_slack(f"#{channel}", f"{header}\n\n{text}")
    await _dm_subscribers(f"{header}\n\n{text}")
    logger.info("[Digest] Weekly digest sent (%d meetings)", len(analyses))


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
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", "")).messages.create(
                model=_MODEL,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            ),
        )
        text = response.content[0].text
    except Exception as exc:
        logger.warning("[Digest] Agenda generation failed: %s", exc)
        return

    header = "📋 *회의 어젠다 후보*" if lang == "ko" else "📋 *Suggested Meeting Agenda*"
    channel = os.getenv("DIGEST_CHANNEL", os.getenv("SLACK_BRIEF_CHANNEL", "general"))
    await _post_to_slack(f"#{channel}", f"{header}\n\n{text}")
