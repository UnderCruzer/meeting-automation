import asyncio
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import auth
from app.routers.workspace import router as workspace_router
from app.services import retention
from app.services.accounts import Accounts
from app.services.audit import AuditLog
from app.services.workspace import Workspace
from app.storage.local import LocalStorage

PW = "correct-horse-battery"
JOB = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_MODE", "standalone")
    auth._failures.clear()
    app = FastAPI()
    app.state.accounts = Accounts(tmp_path)
    app.state.workspace = Workspace(tmp_path)
    app.state.storage = LocalStorage(tmp_path)
    app.state.audit = AuditLog(tmp_path)
    app.state.accounts.create("admin", PW, role="admin", must_change=False)
    app.state.accounts.create("minsu", "member-pass-1", role="member", must_change=False)
    app.include_router(auth.router)
    app.include_router(workspace_router)
    return app


def _login(client, username, password):
    return {"X-Session-Token": client.post("/auth/login", json={"username": username, "password": password}).json()["token"]}


def _actions(app):
    return [(e["action"], e["username"]) for e in reversed(app.state.audit.recent())]


def test_decision_records_actor_and_audit_survives_deletion(app):
    client = TestClient(app)
    member = _login(client, "minsu", "member-pass-1")
    app.state.workspace.create(JOB, "주간 회의", uploaded_by="minsu")
    app.state.workspace.finish(JOB, {})
    assert client.post(f"/workspace/jobs/{JOB}/decision", json={"status": "approved"}, headers=member).status_code == 200
    job = app.state.workspace.list()[0]
    assert (job["uploaded_by"], job["decided_by"]) == ("minsu", "minsu") and job["decided_at"]
    assert client.delete(f"/workspace/jobs/{JOB}", headers=member).status_code == 200
    events = app.state.audit.recent()
    assert [(e["action"], e["title"]) for e in events[:2]] == [("delete", "주간 회의"), ("approve", "주간 회의")]
    assert app.state.workspace.list() == []


def test_auth_events_and_admin_only_audit_view(app):
    client = TestClient(app)
    client.post("/auth/login", json={"username": "minsu", "password": "wrong-password"})
    member = _login(client, "minsu", "member-pass-1")
    admin = _login(client, "admin", PW)
    uid = next(u["id"] for u in client.get("/auth/users", headers=admin).json() if u["username"] == "minsu")
    client.patch(f"/auth/users/{uid}", json={"role": "admin"}, headers=admin)
    client.post("/auth/logout", headers=admin)
    assert _actions(app) == [("login_failed", "minsu"), ("login", "minsu"), ("login", "admin"),
                             ("user_update", "admin"), ("logout", "admin")]
    assert "role=admin" in app.state.audit.recent()[1]["detail"]
    assert client.get("/auth/audit", headers=member).status_code == 200  # promoted to admin above
    demoted = _login(client, "admin", PW)
    client.patch(f"/auth/users/{uid}", json={"role": "member"}, headers=demoted)
    assert client.get("/auth/audit", headers=member).status_code == 403
    assert all(PW not in str(e) for e in client.get("/auth/audit", headers=demoted).json())


def test_purge_is_audited_as_system(app, monkeypatch):
    monkeypatch.setenv("MEETING_RETENTION_DAYS", "1")
    app.state.workspace.create(JOB, "오래된 회의")
    app.state.workspace.finish(JOB, {})
    with app.state.workspace.connect() as db:
        db.execute("UPDATE jobs SET created_at=datetime('now','-3 days')")
    asyncio.run(retention.purge_expired(app.state.workspace, app.state.storage, app.state.audit))
    event = app.state.audit.recent()[0]
    assert (event["action"], event["username"], event["title"]) == ("purge", "system", "오래된 회의")


def test_old_jobs_table_is_migrated(tmp_path):
    db = sqlite3.connect(tmp_path / "workspace.sqlite3")
    db.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL, summary TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    db.execute("INSERT INTO jobs(id,title,status) VALUES ('old','이전 회의','review')")
    db.commit(); db.close()
    store = Workspace(tmp_path)
    assert store.list()[0]["uploaded_by"] is None
    assert store.decide("old", "rejected", "admin")
    assert store.list()[0]["decided_by"] == "admin"


def test_unknown_action_rejected(tmp_path):
    with pytest.raises(ValueError):
        AuditLog(tmp_path).record("hack", "x")
