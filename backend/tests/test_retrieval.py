"""Unit tests for retrieval service — bounded context fetch from Jira/Confluence/Slack."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.analysis import ActionItem, OrchestratorOutput
from app.services.retrieval import _build_keywords, retrieve_context


def _make_analysis(**kwargs) -> OrchestratorOutput:
    defaults = dict(
        meeting_id="m1",
        topics=["배포 일정", "API 설계"],
        decisions=["다음 주 배포 확정"],
        action_items=[ActionItem(description="배포 스크립트 작성", assignee="김개발")],
        participants_mentioned=["김개발"],
        summary_ko="요약.",
        summary_en="Summary.",
        confidence=0.8,
        routing=["jira", "confluence", "slack"],
    )
    defaults.update(kwargs)
    return OrchestratorOutput(**defaults)


# ── _build_keywords ───────────────────────────────────────────────────────────

class TestBuildKeywords:
    def test_includes_topics(self):
        analysis = _make_analysis()
        kw = _build_keywords(analysis)
        assert "배포 일정" in kw

    def test_includes_action_item_description(self):
        analysis = _make_analysis()
        kw = _build_keywords(analysis)
        assert "배포 스크립트" in kw

    def test_no_double_quotes(self):
        analysis = _make_analysis(topics=['topic with "quotes"'])
        kw = _build_keywords(analysis)
        assert '"' not in kw

    def test_max_200_chars(self):
        long_topics = [f"topic number {i}" * 5 for i in range(20)]
        analysis = _make_analysis(topics=long_topics)
        kw = _build_keywords(analysis)
        assert len(kw) <= 200

    def test_empty_analysis(self):
        analysis = _make_analysis(topics=[], action_items=[])
        kw = _build_keywords(analysis)
        assert isinstance(kw, str)


# ── retrieve_context: skips when no credentials ───────────────────────────────

class TestRetrieveContextNoCreds:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_credentials(self):
        """All sources should silently skip when env vars are unset."""
        with patch.dict("os.environ", {}, clear=True):
            analysis = _make_analysis()
            ctx = await retrieve_context(analysis)
        assert ctx.meeting_id == "m1"
        assert ctx.items == []
        assert ctx.sources_searched == []

    @pytest.mark.asyncio
    async def test_returns_context_for_empty_routing(self):
        analysis = _make_analysis(routing=[])
        ctx = await retrieve_context(analysis)
        assert ctx.items == []
        assert ctx.sources_searched == []


# ── retrieve_context: mocked HTTP responses ───────────────────────────────────

class TestRetrieveContextMocked:
    @pytest.mark.asyncio
    async def test_jira_items_returned(self):
        jira_response = {
            "issues": [
                {
                    "key": "PROJ-1",
                    "fields": {
                        "summary": "배포 스크립트 작성",
                        "description": "자동 배포 구성 필요",
                        "status": {"name": "Open"},
                    },
                }
            ]
        }

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = jira_response

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        env = {
            "JIRA_BASE_URL": "https://jira.example.com",
            "JIRA_PROJECT_KEY": "PROJ",
            "JIRA_API_TOKEN": "token",
            "JIRA_EMAIL": "user@example.com",
        }

        with patch.dict("os.environ", env):
            with patch("httpx.AsyncClient", return_value=mock_client):
                analysis = _make_analysis(routing=["jira"])
                ctx = await retrieve_context(analysis)

        assert len(ctx.items) == 1
        assert ctx.items[0].source == "jira"
        assert ctx.items[0].id == "PROJ-1"
        assert "jira" in ctx.sources_searched

    @pytest.mark.asyncio
    async def test_failed_source_excluded_from_searched(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("connection error")
        mock_resp.json.return_value = {}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        env = {
            "JIRA_BASE_URL": "https://jira.example.com",
            "JIRA_PROJECT_KEY": "PROJ",
            "JIRA_API_TOKEN": "token",
            "JIRA_EMAIL": "user@example.com",
        }

        with patch.dict("os.environ", env):
            with patch("httpx.AsyncClient", return_value=mock_client):
                analysis = _make_analysis(routing=["jira"])
                ctx = await retrieve_context(analysis)

        assert ctx.items == []
        assert "jira" not in ctx.sources_searched

    @pytest.mark.asyncio
    async def test_confluence_items_returned(self):
        confluence_response = {
            "results": [
                {
                    "id": "12345",
                    "title": "배포 가이드",
                    "excerpt": "배포 절차 문서",
                    "_links": {"webui": "/wiki/spaces/DOC/pages/12345"},
                }
            ]
        }

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = confluence_response

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        env = {
            "CONFLUENCE_BASE_URL": "https://confluence.example.com",
            "CONFLUENCE_SPACE_KEY": "DOC",
            "CONFLUENCE_API_TOKEN": "token",
            "CONFLUENCE_EMAIL": "user@example.com",
        }

        with patch.dict("os.environ", env):
            with patch("httpx.AsyncClient", return_value=mock_client):
                analysis = _make_analysis(routing=["confluence"])
                ctx = await retrieve_context(analysis)

        assert len(ctx.items) == 1
        assert ctx.items[0].source == "confluence"
        assert ctx.items[0].title == "배포 가이드"
