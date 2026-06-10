"""
Timezone Scheduler — Issue #18

즉시/예약 발송 분기 및 NA/EU/APAC 지역별 근무시간 정책.

Usage:
    from app.services.timezone_scheduler import resolve_send_time, Region

    send_at, region = resolve_send_time(participants)
    # send_at: ISO datetime string (UTC) — None means send immediately
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# ── Region definition ─────────────────────────────────────────────────────────

class Region(str, Enum):
    APAC = "APAC"   # Asia/Pacific (KR, JP, AU, SG, …)
    EU   = "EU"     # Europe (CET, GMT, …)
    NA   = "NA"     # North America (ET, CT, PT, …)
    UNKNOWN = "UNKNOWN"


# ── Timezone → Region mapping ─────────────────────────────────────────────────

_TZ_TO_REGION: dict[str, Region] = {
    # APAC
    "Asia/Seoul":       Region.APAC,
    "Asia/Tokyo":       Region.APAC,
    "Asia/Singapore":   Region.APAC,
    "Asia/Shanghai":    Region.APAC,
    "Asia/Hong_Kong":   Region.APAC,
    "Australia/Sydney": Region.APAC,
    "Pacific/Auckland": Region.APAC,
    # EU
    "Europe/London":    Region.EU,
    "Europe/Paris":     Region.EU,
    "Europe/Berlin":    Region.EU,
    "Europe/Amsterdam": Region.EU,
    "Europe/Madrid":    Region.EU,
    "Europe/Rome":      Region.EU,
    "Europe/Warsaw":    Region.EU,
    "Europe/Stockholm": Region.EU,
    # NA
    "America/New_York":    Region.NA,
    "America/Chicago":     Region.NA,
    "America/Denver":      Region.NA,
    "America/Los_Angeles": Region.NA,
    "America/Toronto":     Region.NA,
    "America/Vancouver":   Region.NA,
}

# Working-hours window per region (local time, inclusive)
_WORK_HOURS: dict[Region, tuple[int, int]] = {
    Region.APAC: (9, 18),   # 09:00–18:00 KST
    Region.EU:   (9, 17),   # 09:00–17:00 CET
    Region.NA:   (9, 17),   # 09:00–17:00 ET
    Region.UNKNOWN: (9, 18),
}

# Representative timezone per region (used for schedule calculation)
_REGION_TZ: dict[Region, str] = {
    Region.APAC:    "Asia/Seoul",
    Region.EU:      "Europe/Paris",
    Region.NA:      "America/New_York",
    Region.UNKNOWN: "Asia/Seoul",
}


# ── Public API ────────────────────────────────────────────────────────────────

@dataclass
class SendSchedule:
    region: Region
    send_at: str | None     # ISO 8601 UTC — None = send immediately
    local_time: str         # human-readable local time for logging
    scheduled: bool         # True if deferred


def detect_region(participant_timezones: list[str]) -> Region:
    """Majority-vote region from a list of IANA timezone strings."""
    counts: dict[Region, int] = {r: 0 for r in Region}
    for tz in participant_timezones:
        region = _TZ_TO_REGION.get(tz, Region.UNKNOWN)
        counts[region] += 1

    # Exclude UNKNOWN from majority unless it's the only one
    known = {r: c for r, c in counts.items() if r != Region.UNKNOWN and c > 0}
    if not known:
        return Region.APAC   # default to APAC (primary office)

    return max(known, key=lambda r: known[r])


def resolve_send_time(
    participant_timezones: list[str],
    now_utc: datetime | None = None,
) -> SendSchedule:
    """
    Determine when to send a message for the given participants.

    If current local time is within working hours → send immediately.
    Otherwise → schedule for next working-hours start.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    region = detect_region(participant_timezones)
    tz_name = os.getenv(f"REGION_TZ_{region.value}", _REGION_TZ[region])

    try:
        local_tz = ZoneInfo(tz_name)
    except Exception:
        logger.warning("[Scheduler] Unknown timezone %s — falling back to Asia/Seoul", tz_name)
        local_tz = ZoneInfo("Asia/Seoul")

    local_now = now_utc.astimezone(local_tz)
    work_start, work_end = _WORK_HOURS.get(region, (9, 18))

    if work_start <= local_now.hour < work_end:
        # Within working hours — send immediately
        return SendSchedule(
            region=region,
            send_at=None,
            local_time=local_now.strftime("%Y-%m-%d %H:%M %Z"),
            scheduled=False,
        )

    # Outside working hours — schedule for next work_start
    next_start = local_now.replace(hour=work_start, minute=0, second=0, microsecond=0)
    if local_now.hour >= work_end:
        # Past end of day → next calendar day
        next_start += timedelta(days=1)
    # Skip weekends (Mon=0 … Sun=6)
    while next_start.weekday() >= 5:
        next_start += timedelta(days=1)

    send_at_utc = next_start.astimezone(timezone.utc)
    return SendSchedule(
        region=region,
        send_at=send_at_utc.isoformat(),
        local_time=next_start.strftime("%Y-%m-%d %H:%M %Z"),
        scheduled=True,
    )


def cancel_scheduled(job_id: str) -> bool:
    """
    Mark a scheduled send as cancelled.

    MVP: write_queue skips tasks where schedule_time is set to 'cancelled'.
    Returns True always (no persistent store in MVP).
    """
    logger.info("[Scheduler] Cancelling scheduled send for job %s", job_id)
    # In MVP the write_queue checks schedule_time; caller should update approval_store
    # with schedule_time="cancelled" to prevent dispatch.
    return True
