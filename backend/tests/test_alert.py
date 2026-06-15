"""Unit tests for admin alert service."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.alert import _build_message, _resolve_target, send_failure_alert


class TestBuildMessage:
    def test_contains_job_id(self):
        msg = _build_message("job-123", "jira", "mtg-001", "timeout")
        assert "job-123" in msg

    def test_contains_artifact(self):
        msg = _build_message("job-123", "jira", "mtg-001", "timeout")
        assert "jira" in msg

    def test_contains_meeting_id(self):
        msg = _build_message("job-123", "jira", "mtg-001", "timeout")
        assert "mtg-001" in msg

    def test_contains_error(self):
        msg = _build_message("job-123", "jira", "mtg-001", "max retries exceeded")
        assert "max retries exceeded" in msg

    def test_contains_alert_emoji(self):
        msg = _build_message("job-123", "slack", "mtg-002", "timeout")
        assert ":rotating_light:" in msg

    def test_all_artifact_types(self):
        for artifact in ("jira", "confluence", "slack", "pdf"):
            msg = _build_message("j1", artifact, "m1", "err")
            assert artifact in msg


class TestResolveTarget:
    def test_returns_user_id_when_set(self, monkeypatch):
        monkeypatch.setenv("SLACK_ADMIN_USER_ID", "U0123456789")
        assert _resolve_target() == "U0123456789"

    def test_returns_channel_when_no_user_id(self, monkeypatch):
        monkeypatch.delenv("SLACK_ADMIN_USER_ID", raising=False)
        monkeypatch.setenv("SLACK_ALERT_CHANNEL", "ops-alerts")
        assert _resolve_target() == "#ops-alerts"

    def test_defaults_to_general_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("SLACK_ADMIN_USER_ID", raising=False)
        monkeypatch.delenv("SLACK_ALERT_CHANNEL", raising=False)
        assert _resolve_target() == "#general"

    def test_user_id_takes_priority_over_channel(self, monkeypatch):
        monkeypatch.setenv("SLACK_ADMIN_USER_ID", "U999")
        monkeypatch.setenv("SLACK_ALERT_CHANNEL", "ops")
        assert _resolve_target() == "U999"


class TestSendFailureAlert:
    @pytest.mark.asyncio
    async def test_skips_when_no_token(self, monkeypatch, caplog):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        import logging
        with caplog.at_level(logging.WARNING):
            await send_failure_alert("j1", "jira", "m1", "timeout")
        assert "SLACK_BOT_TOKEN" in caplog.text

    @pytest.mark.asyncio
    async def test_posts_to_slack_when_token_set(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setenv("SLACK_ADMIN_USER_ID", "U123")

        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "ts": "123.456"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            await send_failure_alert("j1", "jira", "m1", "timeout")

            mock_client.post.assert_called_once()
            call_kwargs = mock_client.post.call_args
            assert call_kwargs[1]["json"]["channel"] == "U123"

    @pytest.mark.asyncio
    async def test_logs_slack_api_error(self, monkeypatch, caplog):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.delenv("SLACK_ADMIN_USER_ID", raising=False)

        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": False, "error": "channel_not_found"}
        mock_response.raise_for_status = MagicMock()

        import logging
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with caplog.at_level(logging.ERROR):
                await send_failure_alert("j1", "slack", "m1", "err")

        assert "channel_not_found" in caplog.text

    @pytest.mark.asyncio
    async def test_does_not_raise_on_network_error(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=Exception("network error"))
            mock_client_cls.return_value = mock_client

            # Should not raise
            await send_failure_alert("j1", "jira", "m1", "timeout")
