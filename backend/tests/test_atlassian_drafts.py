"""Jira / Confluence drafts prepared for review (workflow 10·12·13) and kept with the meeting."""
import asyncio
from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.models.analysis import ActionItem, OrchestratorOutput
from app.models.drafts import JiraDraftResult, JiraIssueDraft
from app.models.retrieval import RetrievalContext, RetrievalItem
from app.models.summary import MeetingSummary
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.routers import upload
from app.services import atlassian_drafts
from app.services.llm import LLMUnavailable
from app.services.workspace import Workspace

TOKENS = {"[PERSON_1]": "김민수"}
ANALYSIS = OrchestratorOutput(
    meeting_id="m", topics=["릴리스 일정"], decisions=["10월 출시"],
    action_items=[ActionItem(description="릴리스 노트 작성", assignee="[PERSON_1]")],
    participants_mentioned=["[PERSON_1]"], summary_ko="[PERSON_1] 님이 릴리스 노트 작성", summary_en="Release notes",
    confidence=0.9, routing=["slack"])
MASKED = MeetingSummary(meeting_id="m", summary_ko="[PERSON_1] 님이 릴리스 노트 작성", summary_en="Release notes",
                        decisions=[], action_items=[{"description": "릴리스 노트 작성", "assignee": "[PERSON_1]",
                                                     "due_date": "금요일", "priority": "high"}],
                        quality_flags=[], quality_ok=True)
RELATED = RetrievalContext(meeting_id="m", sources_searched=["jira", "confluence"], items=[
    RetrievalItem(source="jira", id="OPS-3", title="김민수 팀장 요청: 릴리스 체크리스트", url="https://team.atlassian.net/browse/OPS-3",
                  snippet="", status="To Do"),
    RetrievalItem(source="confluence", id="77", title="릴리스 절차", url="https://team.atlassian.net/wiki/spaces/DOC/pages/77",
                  snippet="절차"),
])


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("ATLASSIAN_BASE_URL", "https://team.atlassian.net")
    monkeypatch.setenv("ATLASSIAN_EMAIL", "me@example.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "test-token")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "OPS")
    monkeypatch.setenv("CONFLUENCE_SPACE_KEY", "DOC")
    for name in ("JIRA_API_TOKEN", "CONFLUENCE_API_TOKEN", "JIRA_BASE_URL", "CONFLUENCE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    search = AsyncMock(return_value=RELATED)
    monkeypatch.setattr(atlassian_drafts, "retrieve_context", search)
    return search


def _jira(*drafts):
    return AsyncMock(return_value=JiraDraftResult(meeting_id="m", drafts=[JiraIssueDraft(**d) for d in drafts]))


def test_not_configured_means_no_drafts(monkeypatch):
    for name in ("ATLASSIAN_API_TOKEN", "JIRA_API_TOKEN", "CONFLUENCE_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert asyncio.run(atlassian_drafts.prepare(ANALYSIS, MASKED, TOKENS, "출시 회의", date(2026, 10, 3))) is None


def test_drafts_from_search_results(configured, monkeypatch):
    jira = _jira(
        {"action": "create", "summary": "[PERSON_1] 릴리스 노트 작성", "description": "담당: [PERSON_1]", "priority": "High"},
        {"action": "comment", "existing_key": "OPS-3", "summary": "체크리스트 갱신", "description": "회의에서 확정"},
        {"action": "comment", "existing_key": "OPS-99", "summary": "찾지 못한 이슈", "description": "x"},
        {"action": "comment", "existing_key": "HR-1", "summary": "다른 프로젝트", "description": "x"},
    )
    monkeypatch.setattr(atlassian_drafts, "generate_jira_drafts", jira)
    drafts = asyncio.run(atlassian_drafts.prepare(ANALYSIS, MASKED, TOKENS, "출시 회의", date(2026, 10, 3)))

    assert configured.call_args.kwargs["sources"] == ["jira", "confluence"]
    assert [r["id"] for r in drafts["related"]] == ["OPS-3", "77"]
    items = drafts["jira"]["drafts"]
    # Names restored for reviewers; comments only on issues the search found in the project.
    assert items[0]["summary"] == "김민수 릴리스 노트 작성" and items[0]["include"] is True
    assert [(d["action"], d["existing_key"]) for d in items] == [
        ("create", ""), ("comment", "OPS-3"), ("create", ""), ("create", "")]
    assert drafts["confluence"]["title"] == "회의록 2026-10-03 — 출시 회의"

    # Titles from Jira did not pass the transcript guard: names and PII are masked before the LLM.
    protect = jira.call_args.kwargs["protect"]
    assert protect("김민수 팀장 요청 kim@example.com") == "[PERSON_1] 팀장 요청 [MASKED_EMAIL]"


def test_llm_busy_keeps_the_meeting_reviewable(configured, monkeypatch):
    monkeypatch.setattr(atlassian_drafts, "generate_jira_drafts", AsyncMock(side_effect=LLMUnavailable("busy")))
    drafts = asyncio.run(atlassian_drafts.prepare(ANALYSIS, MASKED, TOKENS, "출시 회의", date(2026, 10, 3)))
    assert drafts["jira"] == {"drafts": [], "status": None, "error": None, "generation_error": "LLM_BUSY"}
    assert drafts["confluence"]["include"] is True


def test_search_failure_still_drafts(configured, monkeypatch):
    configured.side_effect = RuntimeError("network")
    monkeypatch.setattr(atlassian_drafts, "generate_jira_drafts", _jira(
        {"action": "comment", "existing_key": "OPS-3", "summary": "갱신", "description": "x"}))
    drafts = asyncio.run(atlassian_drafts.prepare(ANALYSIS, MASKED, TOKENS, "출시 회의", date(2026, 10, 3)))
    assert drafts["related"] == []
    assert drafts["jira"]["drafts"][0]["action"] == "create"


def _run_pipeline(tmp_path, monkeypatch, quality_ok=True):
    monkeypatch.setenv("WORKSPACE_MODE", "standalone")
    store = Workspace(tmp_path)
    store.create("abc", "출시 회의")
    text = "김민수 팀장 릴리스 노트 작성 부탁드립니다"
    transcript = TranscriptResult(meetingId="m", language="ko", duration=60, backend="test", full_text=text,
                                  segments=[TranscriptSegment(start=0, end=60, text=text)])
    monkeypatch.setattr(upload, "transcribe", AsyncMock(return_value=transcript))
    monkeypatch.setattr(upload, "analyse", AsyncMock(return_value=ANALYSIS))
    for name in ("save_guard_report", "save_analysis", "save_summary"):
        monkeypatch.setattr(upload, name, AsyncMock())
    real_build = upload.build_summary
    monkeypatch.setattr(upload, "build_summary", lambda a, t: real_build(a, t).model_copy(update={"quality_ok": quality_ok}))
    asyncio.run(upload._run_stt_and_guard(tmp_path / "abc.wav", "m/abc.wav", "m", tmp_path))
    return store.get("abc")


def test_pipeline_stores_drafts_with_the_meeting(configured, tmp_path, monkeypatch):
    jira = _jira({"action": "create", "summary": "[PERSON_1] 릴리스 노트", "description": "x"})
    monkeypatch.setattr(atlassian_drafts, "generate_jira_drafts", jira)
    job = _run_pipeline(tmp_path, monkeypatch)
    assert job["status"] == "review"
    assert job["drafts"]["jira"]["drafts"][0]["summary"] == "김민수 릴리스 노트"
    # The draft LLM saw only the pseudonymised summary.
    assert "김민수" not in jira.call_args.args[0].model_dump_json()


def test_low_quality_meeting_gets_no_drafts(configured, tmp_path, monkeypatch):
    monkeypatch.setattr(atlassian_drafts, "generate_jira_drafts", _jira())
    job = _run_pipeline(tmp_path, monkeypatch, quality_ok=False)
    assert job["status"] == "review" and job["drafts"] is None
    configured.assert_not_called()


def test_drafts_edits_and_restart_recovery(tmp_path):
    store = Workspace(tmp_path)
    store.create("abc", "회의")
    store.finish("abc", {"summary_ko": "s", "action_items": []}, 0.9,
                 {"related": [], "jira": {"drafts": [{"summary": "a", "include": True}], "status": None},
                  "confluence": {"title": "t", "include": True, "status": None}})
    assert store.mutate_drafts("abc", lambda d: d["jira"]["drafts"][0].update(include=False), status="review")
    assert store.get("abc")["drafts"]["jira"]["drafts"][0]["include"] is False
    assert not store.mutate_drafts("abc", lambda d: None, status="approved")
    assert not store.mutate_drafts("abc", lambda d: False)

    store.mutate_drafts("abc", lambda d: d["confluence"].update(status="queued"))
    Workspace(tmp_path).recover()
    confluence = store.get("abc")["drafts"]["confluence"]
    assert confluence["status"] == "failed" and "재시작" in confluence["error"]
    assert store.get("abc")["drafts"]["jira"]["status"] is None
