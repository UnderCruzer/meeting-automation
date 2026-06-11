"""Unit tests for regional_delivery service."""
import pytest
from app.services.timezone_scheduler import Region, SendSchedule
from app.services.regional_delivery import (
    _channel,
    _select_language,
    build_regional_message,
)


def _schedule(region: Region) -> SendSchedule:
    return SendSchedule(
        region=region,
        send_at=None,
        local_time="2026-06-10 10:00 KST",
        scheduled=False,
    )


class TestSelectLanguage:
    def test_apac_returns_korean(self):
        assert _select_language(Region.APAC) == "ko"

    def test_eu_returns_english(self):
        assert _select_language(Region.EU) == "en"

    def test_na_returns_english(self):
        assert _select_language(Region.NA) == "en"

    def test_unknown_returns_english(self):
        assert _select_language(Region.UNKNOWN) == "en"


class TestChannel:
    def test_apac_default_channel(self):
        ch = _channel(Region.APAC)
        assert "apac" in ch.lower()

    def test_eu_default_channel(self):
        ch = _channel(Region.EU)
        assert "eu" in ch.lower()

    def test_na_default_channel(self):
        ch = _channel(Region.NA)
        assert "na" in ch.lower()

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("SLACK_CHANNEL_APAC", "custom-apac-channel")
        assert _channel(Region.APAC) == "custom-apac-channel"


class TestBuildRegionalMessage:
    def test_apac_uses_korean_summary(self):
        msg = build_regional_message(
            summary_ko="한국어 요약",
            summary_en="English summary",
            meeting_id="m1",
            schedule=_schedule(Region.APAC),
        )
        assert "한국어 요약" in msg.text
        assert "English summary" not in msg.text
        assert msg.lang == "ko"

    def test_eu_uses_english_summary(self):
        msg = build_regional_message(
            summary_ko="한국어 요약",
            summary_en="English summary",
            meeting_id="m1",
            schedule=_schedule(Region.EU),
        )
        assert "English summary" in msg.text
        assert "한국어 요약" not in msg.text
        assert msg.lang == "en"

    def test_na_uses_english_summary(self):
        msg = build_regional_message(
            summary_ko="한국어 요약",
            summary_en="English summary",
            meeting_id="m1",
            schedule=_schedule(Region.NA),
        )
        assert msg.lang == "en"

    def test_meeting_id_in_message(self):
        msg = build_regional_message(
            summary_ko="요약",
            summary_en="summary",
            meeting_id="test-meeting-42",
            schedule=_schedule(Region.APAC),
        )
        assert "test-meeting-42" in msg.text

    def test_thread_ts_attached(self):
        msg = build_regional_message(
            summary_ko="요약",
            summary_en="summary",
            meeting_id="m1",
            schedule=_schedule(Region.APAC),
            thread_ts="1234567890.123456",
        )
        assert msg.thread_ts == "1234567890.123456"

    def test_new_message_when_no_thread_ts(self):
        msg = build_regional_message(
            summary_ko="요약",
            summary_en="summary",
            meeting_id="m1",
            schedule=_schedule(Region.APAC),
        )
        assert msg.thread_ts is None

    def test_channel_set_correctly(self):
        msg = build_regional_message(
            summary_ko="요약",
            summary_en="summary",
            meeting_id="m1",
            schedule=_schedule(Region.EU),
        )
        assert "eu" in msg.channel.lower()
