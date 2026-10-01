import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.auth import current_user
from app.routers.workspace import router
from app.services.audit import AuditLog
from app.services.workspace import Workspace
from app.storage.local import LocalStorage

JOB = "0123456789abcdef0123456789abcdef"
SUMMARY = {"meeting_id": "m", "summary_ko": "s", "summary_en": "s", "decisions": [], "quality_flags": [], "quality_ok": True,
           "action_items": [{"description": "보고서", "assignee": "김민수", "due_date": "내일", "priority": "high", "citation_text": ""}]}


@pytest.fixture
def app(tmp_path):
    app = FastAPI()
    app.state.workspace, app.state.storage, app.state.audit = Workspace(tmp_path), LocalStorage(tmp_path), AuditLog(tmp_path)
    app.include_router(router)
    app.dependency_overrides[current_user] = lambda: None
    app.state.workspace.create(JOB, "회의")
    app.state.workspace.finish(JOB, SUMMARY)
    return app


def test_done_only_after_approval_and_toggle(app):
    c = TestClient(app)
    assert c.patch(f"/workspace/jobs/{JOB}/action-items/0", json={"done": True}).status_code == 409
    app.state.workspace.decide(JOB, "approved", "admin")
    assert c.patch(f"/workspace/jobs/{JOB}/action-items/0", json={"done": True}).status_code == 200
    item = app.state.workspace.get(JOB)["summary"]["action_items"][0]
    assert item["done"] is True and item["done_at"]
    assert app.state.audit.recent()[0]["action"] == "task_done"
    c.patch(f"/workspace/jobs/{JOB}/action-items/0", json={"done": False})
    item = app.state.workspace.get(JOB)["summary"]["action_items"][0]
    assert item["done"] is False and item["done_at"] is None
    assert c.patch(f"/workspace/jobs/{JOB}/action-items/5", json={"done": True}).status_code == 409


def test_due_resolved_relative_to_meeting_day(app, monkeypatch):
    monkeypatch.setenv("DEFAULT_TIMEZONE", "Asia/Seoul")
    monkeypatch.delenv("WORKSPACE_TIMEZONES", raising=False)
    with app.state.workspace.connect() as db:   # 2026-09-30 23:30 UTC = 10/1 08:30 KST
        db.execute("UPDATE jobs SET created_at='2026-09-30 23:30:00'")
    assert app.state.workspace.get(JOB)["summary"]["action_items"][0]["due"] == "2026-10-02"
