import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import bootstrap_admin
from app.routers import auth
from app.routers.workspace import router as workspace_router
from app.services.accounts import Accounts
from app.services.workspace import Workspace
from app.storage.local import LocalStorage

PW = "correct-horse-battery"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_MODE", "standalone")
    auth._failures.clear()
    app = FastAPI()
    app.state.accounts = Accounts(tmp_path)
    app.state.workspace = Workspace(tmp_path)
    app.state.storage = LocalStorage(tmp_path)
    app.state.accounts.create("admin", PW, role="admin", must_change=False)
    app.include_router(auth.router)
    app.include_router(workspace_router)
    return TestClient(app)


def _login(client, username="admin", password=PW):
    res = client.post("/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"X-Session-Token": res.json()["token"]}


def test_password_is_hashed_and_wrong_password_rejected(client, tmp_path):
    import sqlite3
    stored = sqlite3.connect(tmp_path / "workspace.sqlite3").execute("SELECT password_hash FROM users").fetchone()[0]
    assert PW not in stored and stored.startswith("scrypt$")
    assert client.post("/auth/login", json={"username": "admin", "password": "nope-nope-nope"}).status_code == 401
    assert client.post("/auth/login", json={"username": "ghost", "password": PW}).status_code == 401


def test_session_required_for_workspace_and_token_only_stored_hashed(client, tmp_path):
    import sqlite3
    assert client.get("/workspace/jobs").status_code == 401
    headers = _login(client)
    assert client.get("/workspace/jobs", headers=headers).status_code == 200
    stored = sqlite3.connect(tmp_path / "workspace.sqlite3").execute("SELECT token_hash FROM sessions").fetchone()[0]
    assert headers["X-Session-Token"] != stored
    assert client.get("/auth/me", headers=headers).json()["user"]["username"] == "admin"
    client.post("/auth/logout", headers=headers)
    assert client.get("/workspace/jobs", headers=headers).status_code == 401


def test_username_lockout_after_repeated_failures(client):
    for _ in range(5):
        client.post("/auth/login", json={"username": "admin", "password": "wrong-password"})
    assert client.post("/auth/login", json={"username": "admin", "password": PW}).status_code == 429


def test_admin_manages_users_and_disabling_revokes_sessions(client):
    admin = _login(client)
    res = client.post("/auth/users", json={"username": "Minsu.Kim", "password": "initial-pass-1"}, headers=admin)
    assert res.status_code == 200
    member_id = res.json()["id"]
    assert res.json()["username"] == "minsu.kim" and res.json()["mustChangePassword"] is True
    member = _login(client, "minsu.kim", "initial-pass-1")
    assert client.get("/auth/users", headers=member).status_code == 403
    assert client.post("/auth/users", json={"username": "x" * 3, "password": "short"}, headers=admin).status_code == 400
    assert client.patch(f"/auth/users/{member_id}", json={"active": False}, headers=admin).status_code == 200
    assert client.get("/workspace/jobs", headers=member).status_code == 401
    assert client.post("/auth/login", json={"username": "minsu.kim", "password": "initial-pass-1"}).status_code == 401


def test_last_admin_and_self_demotion_are_refused(client):
    admin = _login(client)
    me = client.get("/auth/me", headers=admin).json()["user"]
    assert client.patch(f"/auth/users/{me['id']}", json={"role": "member"}, headers=admin).status_code == 400
    assert client.patch(f"/auth/users/{me['id']}", json={"active": False}, headers=admin).status_code == 400


def test_password_change_signs_out_other_sessions(client):
    first, second = _login(client), _login(client)
    res = client.post("/auth/password", json={"current": PW, "new": "brand-new-password"}, headers=first)
    assert res.status_code == 200
    assert client.get("/workspace/jobs", headers=first).status_code == 200
    assert client.get("/workspace/jobs", headers=second).status_code == 401
    assert client.post("/auth/password", json={"current": "wrong", "new": "another-password"}, headers=first).status_code == 400


def test_bootstrap_admin_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_MODE", "standalone")
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("WORKSPACE_PASSWORD", raising=False)
    with pytest.raises(RuntimeError):
        bootstrap_admin(Accounts(tmp_path))
    (tmp_path / "b").mkdir()
    monkeypatch.setenv("WORKSPACE_PASSWORD", "legacy-shared-password")
    accounts = Accounts(tmp_path / "b")
    bootstrap_admin(accounts)
    assert accounts.authenticate("workspace", "legacy-shared-password").is_admin
    monkeypatch.setenv("ADMIN_PASSWORD", "ignored-once-users-exist")
    bootstrap_admin(accounts)
    assert accounts.count() == 1


