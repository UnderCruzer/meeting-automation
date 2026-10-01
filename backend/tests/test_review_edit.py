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
SUMMARY = {"meeting_id": "m", "summary_ko": "요약", "summary_en": "Summary", "decisions": [],
           "action_items": [{"description": "보고서 작성", "assignee": "", "due_date": "", "priority": "medium",
                             "citation_start": 3.0, "citation_end": 9.0, "citation_text": "보고서는 제가 쓸게요"}],
           "quality_flags": [], "quality_ok": True}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    app = FastAPI()
    app.state.workspace, app.state.storage, app.state.audit = Workspace(tmp_path), LocalStorage(tmp_path), AuditLog(tmp_path)
    app.include_router(router)
    app.dependency_overrides[current_user] = lambda: None
    app.state.workspace.create(JOB, "주간 회의")
    app.state.workspace.finish(JOB, SUMMARY)
    return app


def test_edit_owner_due_priority_and_add_item_keeps_evidence(app):
    client = TestClient(app)
    item = {**SUMMARY["action_items"][0], "assignee": "김민수", "due_date": "10/10", "priority": "high"}
    res = client.put(f"/workspace/jobs/{JOB}/action-items",
                     json={"items": [item, {"description": "QA 일정 공유", "assignee": "박지은"}]})
    assert res.status_code == 200
    items = app.state.workspace.get(JOB)["summary"]["action_items"]
    assert (items[0]["assignee"], items[0]["priority"], items[0]["citation_text"]) == ("김민수", "high", "보고서는 제가 쓸게요")
    assert {k: v for k, v in items[1].items() if k != "due"} == {
        "description": "QA 일정 공유", "assignee": "박지은", "due_date": "", "priority": "medium",
        "citation_start": 0.0, "citation_end": 0.0, "citation_text": ""}
    assert items[0]["due"] is not None  # "10/10" resolved against the meeting date
    assert app.state.audit.recent()[0]["action"] == "edit"


def test_remove_all_items_allowed(app):
    assert TestClient(app).put(f"/workspace/jobs/{JOB}/action-items", json={"items": []}).status_code == 200
    assert app.state.workspace.get(JOB)["summary"]["action_items"] == []


@pytest.mark.parametrize("items", [
    [{"description": ""}],
    [{"description": "x", "priority": "urgent"}],
    [{"description": "x" * 501}],
    [{"description": "x"}] * 51,
])
def test_invalid_edits_rejected(app, items):
    assert TestClient(app).put(f"/workspace/jobs/{JOB}/action-items", json={"items": items}).status_code == 422


def test_cannot_edit_after_decision(app):
    client = TestClient(app)
    client.post(f"/workspace/jobs/{JOB}/decision", json={"status": "approved"})
    assert client.put(f"/workspace/jobs/{JOB}/action-items", json={"items": []}).status_code == 409


def test_approve_without_slack_post(app, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-only")
    while not write_queue._queue.empty():
        write_queue._queue.get_nowait()
    res = TestClient(app).post(f"/workspace/jobs/{JOB}/decision", json={"status": "approved", "publish_slack": False})
    assert res.status_code == 200 and "publish" not in res.json()
    assert write_queue._queue.empty()
    assert app.state.workspace.get(JOB)["publish_status"] is None
