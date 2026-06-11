"""Unit tests for timezone_scheduler service."""
import pytest
from datetime import datetime, timezone
from app.services.timezone_scheduler import (
    Region,
    detect_region,
    resolve_send_time,
)


class TestDetectRegion:
    def test_korean_timezone_is_apac(self):
        assert detect_region(["Asia/Seoul"]) == Region.APAC

    def test_tokyo_is_apac(self):
        assert detect_region(["Asia/Tokyo"]) == Region.APAC

    def test_london_is_eu(self):
        assert detect_region(["Europe/London"]) == Region.EU

    def test_new_york_is_na(self):
        assert detect_region(["America/New_York"]) == Region.NA

    def test_majority_vote(self):
        # 2 APAC, 1 NA → APAC wins
        assert detect_region(["Asia/Seoul", "Asia/Tokyo", "America/New_York"]) == Region.APAC

    def test_unknown_timezone_defaults_to_apac(self):
        assert detect_region(["Unknown/Zone"]) == Region.APAC

    def test_empty_list_defaults_to_apac(self):
        assert detect_region([]) == Region.APAC

    def test_mixed_known_unknown_uses_known(self):
        result = detect_region(["Unknown/Zone", "Europe/Paris"])
        assert result == Region.EU


class TestResolveSendTime:
    def _utc(self, year, month, day, hour, minute=0) -> datetime:
        return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)

    def test_sends_immediately_during_work_hours_apac(self):
        # 10:00 KST = 01:00 UTC
        now = self._utc(2026, 6, 10, 1, 0)  # Wednesday
        schedule = resolve_send_time(["Asia/Seoul"], now_utc=now)
        assert schedule.scheduled is False
        assert schedule.send_at is None
        assert schedule.region == Region.APAC

    def test_schedules_outside_work_hours_apac(self):
        # 23:00 KST = 14:00 UTC — after work hours
        now = self._utc(2026, 6, 10, 14, 0)  # Wednesday
        schedule = resolve_send_time(["Asia/Seoul"], now_utc=now)
        assert schedule.scheduled is True
        assert schedule.send_at is not None

    def test_sends_immediately_during_work_hours_eu(self):
        # 10:00 CEST (UTC+2) = 08:00 UTC
        now = self._utc(2026, 6, 10, 8, 0)  # Wednesday
        schedule = resolve_send_time(["Europe/Paris"], now_utc=now)
        assert schedule.scheduled is False

    def test_schedules_weekend_to_monday(self):
        # Saturday 22:00 KST = 13:00 UTC — outside work hours on weekend
        now = self._utc(2026, 6, 13, 13, 0)  # Saturday
        schedule = resolve_send_time(["Asia/Seoul"], now_utc=now)
        assert schedule.scheduled is True
        # send_at should be Monday
        send_dt = datetime.fromisoformat(schedule.send_at)
        assert send_dt.weekday() == 0  # Monday

    def test_region_reflected_in_schedule(self):
        now = self._utc(2026, 6, 10, 1, 0)
        schedule = resolve_send_time(["America/New_York"], now_utc=now)
        assert schedule.region == Region.NA

    def test_local_time_string_present(self):
        now = self._utc(2026, 6, 10, 1, 0)
        schedule = resolve_send_time(["Asia/Seoul"], now_utc=now)
        assert schedule.local_time != ""
