"""Review → approve → Jira issues / Confluence page through the Write Queue (#82)."""
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.auth import current_user
from app.routers.workspace import router
from app.services import write_queue
from app.services.audit import AuditLog
from app.services.workspace import Workspace
from app.storage.local import LocalStorage

JOB = "0123456789abcdef0123456789abcdef"
SUMMARY = {"meeting_id": "m", "summary_ko": "출시 일정 확정", "summary_en": "Launch date fixed",
           "decisions": [{"text": "10월 출시"}],
           "action_items": [{"description": "릴리스 노트 작성", "assignee": "김민수", "due_date": "10/10",
                             "priority": "high", "citation_text": ""}],
           "quality_flags": [], "quality_ok": True}
DRAFTS = {
    "related": [{"source": "jira", "id": "OPS-3", "title": "릴리스 체크리스트", "url": "https://team.atlassian.net/browse/OPS-3",
                 "snippet": "", "relevance": 1.0, "status": "To Do"}],
    "jira": {"drafts": [
        {"action": "create", "existing_key": "", "summary": "릴리스 노트 작성", "description": "담당: 김민수",
         "priority": "High", "include": True},
        {"action": "comment", "existing_key": "OPS-3", "summary": "체크리스트 갱신", "description": "확정",
         "priority": "Medium", "include": True},
    ], "status": None, "error": None, "generation_error": None},
    "confluence": {"title": "회의록 2026-10-03 — 출시 회의", "include": True, "status": None, "result": None, "error": None},
}
_real_client = httpx.AsyncClient


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLASSIAN_BASE_URL", "https://team.atlassian.net")
    monkeypatch.setenv("ATLASSIAN_EMAIL", "me@example.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "test-token")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "OPS")
    monkeypatch.setenv("CONFLUENCE_SPACE_KEY", "DOC")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    while not write_queue._queue.empty():
        write_queue._queue.get_nowait()
    requests, state = [], {"fail_jira": False}

    def atlassian(request):
        requests.append(request)
        path = request.url.path
        if path == "/wiki/api/v2/spaces":
            return httpx.Response(200, json={"results": [{"id": "98"}]})
        if path == "/wiki/api/v2/pages":
            return httpx.Response(200, json={"id": "555", "title": json.loads(request.content)["title"],
                                             "_links": {"base": "https://team.atlassian.net/wiki", "webui": "/spaces/DOC/pages/555"}})
        if state["fail_jira"] and path == "/rest/api/3/issue":
            return httpx.Response(400, json={"errorMessages": ["Issue type is invalid"], "errors": {}})
        if path.endswith("/comment"):
            return httpx.Response(201, json={"id": "1"})
        return httpx.Response(201, json={"key": "OPS-10"})

    monkeypatch.setattr(write_queue.httpx, "AsyncClient",
                        lambda **kw: _real_client(transport=httpx.MockTransport(atlassian), **kw))
    app = FastAPI()
    app.state.workspace = Workspace(tmp_path)
    app.state.storage = LocalStorage(tmp_path)
    app.state.audit = AuditLog(tmp_path)
    app.include_router(router)
    app.dependency_overrides[current_user] = lambda: None
    app.state.workspace.create(JOB, "출시 회의")
    app.state.workspace.finish(JOB, SUMMARY, 0.9, json.loads(json.dumps(DRAFTS)))
    return TestClient(app), app, requests, state


def _drain():
    while not write_queue._queue.empty():
        asyncio.run(write_queue._dispatch(write_queue._queue.get_nowait()))


def test_config_reports_connected_products(env):
    client, *_ = env
    assert client.get("/workspace/config").json() == {"slackPublishing": False, "jira": True, "confluence": True}


def test_reviewer_edits_then_approval_creates_only_the_chosen_items(env):
    client, app, requests, _ = env
    edit = {"jira": [{"include": True, "summary": "릴리스 노트 작성 (10/10)", "description": "담당: 김민수"},
                     {"include": False, "summary": "체크리스트 갱신", "description": "확정"}],
            "confluence": {"include": True, "title": "출시 회의록"}}
    assert client.put(f"/workspace/jobs/{JOB}/drafts", json=edit).status_code == 200

    res = client.post(f"/workspace/jobs/{JOB}/decision", json={"status": "approved"}).json()
    assert res["jira"] == {"status": "queued"} and res["confluence"] == {"status": "queued"}
    _drain()

    created = [json.loads(r.content) for r in requests if r.url.path == "/rest/api/3/issue"]
    assert [c["fields"]["summary"] for c in created] == ["릴리스 노트 작성 (10/10)"]
    assert not any(r.url.path.endswith("/comment") for r in requests)   # unchecked draft skipped
    page = json.loads(next(r.content for r in requests if r.url.path == "/wiki/api/v2/pages"))
    assert page["title"] == "출시 회의록" and "릴리스 노트 작성" in page["body"]["value"]

    drafts = app.state.workspace.get(JOB)["drafts"]
    assert drafts["jira"]["status"] == "sent"
    assert drafts["jira"]["drafts"][0]["result"]["url"] == "https://team.atlassian.net/browse/OPS-10"
    assert drafts["confluence"]["result"]["url"] == "https://team.atlassian.net/wiki/spaces/DOC/pages/555"
    actions = [(e["action"], e["detail"]) for e in app.state.audit.recent(20)]
    assert ("publish", "jira sent: OPS-10") in actions


def test_drafts_are_frozen_after_decision(env):
    client, *_ = env
    client.post(f"/workspace/jobs/{JOB}/decision", json={"status": "rejected"})
    res = client.put(f"/workspace/jobs/{JOB}/drafts", json={"confluence": {"include": False, "title": "x"}})
    assert res.status_code == 409


def test_edit_must_cover_every_draft(env):
    client, *_ = env
    res = client.put(f"/workspace/jobs/{JOB}/drafts",
                     json={"jira": [{"include": True, "summary": "하나만", "description": ""}]})
    assert res.status_code == 409


def test_approve_without_atlassian_outputs(env):
    client, app, requests, _ = env
    res = client.post(f"/workspace/jobs/{JOB}/decision",
                      json={"status": "approved", "publish_jira": False, "publish_confluence": False}).json()
    assert "jira" not in res and "confluence" not in res
    _drain()
    assert requests == []


def test_failure_is_shown_and_retry_creates_only_missing_items(env):
    client, app, requests, state = env
    state["fail_jira"] = True
    client.post(f"/workspace/jobs/{JOB}/decision", json={"status": "approved", "publish_confluence": False})
    _drain()
    jira = app.state.workspace.get(JOB)["drafts"]["jira"]
    assert jira["status"] == "failed" and "Issue type is invalid" in jira["error"]

    state["fail_jira"] = False
    assert client.post(f"/workspace/jobs/{JOB}/publish", json={"target": "jira"}).json() == {"status": "queued"}
    _drain()
    jira = app.state.workspace.get(JOB)["drafts"]["jira"]
    assert jira["status"] == "sent" and all(d["result"] for d in jira["drafts"])
    # Nothing left to create: a second retry is refused instead of duplicating issues.
    assert client.post(f"/workspace/jobs/{JOB}/publish", json={"target": "jira"}).status_code == 409


def test_retry_requires_configuration(env, monkeypatch):
    client, *_ = env
    client.post(f"/workspace/jobs/{JOB}/decision", json={"status": "approved", "publish_confluence": False,
                                                         "publish_jira": False})
    monkeypatch.delenv("ATLASSIAN_API_TOKEN")
    res = client.post(f"/workspace/jobs/{JOB}/publish", json={"target": "confluence"})
    assert res.status_code == 409 and "설정" in res.json()["detail"]
