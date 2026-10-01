"""Turn free-text due dates written by the AI or users ("10/10", "7월 3일", "다음 주 금요일")
into calendar dates, relative to the meeting date. Unknown text → None (never guessed)."""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_WEEKDAYS = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
_ISO = re.compile(r"(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})\s*일?")
_MONTH_DAY = re.compile(r"(?<!\d)(\d{1,2})\s*(?:[/.]|월\s*)\s*(\d{1,2})\s*일?(?!\d)")
_WEEKDAY = re.compile(r"(이번\s*주|다음\s*주|다다음\s*주)?\s*([월화수목금토일])요일")


def parse_due(text: str | None, reference: date) -> date | None:
    """Parse `text` relative to `reference` (usually the meeting date)."""
    if not text:
        return None
    t = text.strip()

    if m := _ISO.search(t):
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    if m := _MONTH_DAY.search(t):
        month, day = int(m.group(1)), int(m.group(2))
        candidate = _safe_date(reference.year, month, day)
        # "1/5" written in December means next January.
        if candidate and candidate < reference - timedelta(days=60):
            candidate = _safe_date(reference.year + 1, month, day)
        return candidate

    if "모레" in t:
        return reference + timedelta(days=2)
    if "내일" in t:
        return reference + timedelta(days=1)
    if "오늘" in t or "당일" in t:
        return reference

    if m := _WEEKDAY.search(t):
        week = (m.group(1) or "").replace(" ", "")
        target = _WEEKDAYS[m.group(2)]
        monday = reference - timedelta(days=reference.weekday())
        offset = {"": 0, "이번주": 0, "다음주": 7, "다다음주": 14}[week]
        day = monday + timedelta(days=offset + target)
        if not week and day < reference:  # bare "금요일" already passed → the coming one
            day += timedelta(days=7)
        return day
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def team_timezone() -> ZoneInfo:
    name = (os.getenv("WORKSPACE_TIMEZONES") or os.getenv("DEFAULT_TIMEZONE") or "Asia/Seoul").split(",")[0].strip()
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("Asia/Seoul")


def local_date(sqlite_utc: str | None) -> date | None:
    """SQLite CURRENT_TIMESTAMP (UTC, "YYYY-MM-DD HH:MM:SS") → date in the team's timezone."""
    if not sqlite_utc:
        return None
    try:
        moment = datetime.fromisoformat(sqlite_utc.replace(" ", "T")).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return moment.astimezone(team_timezone()).date()
