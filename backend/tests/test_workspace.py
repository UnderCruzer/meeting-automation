from app.routers.auth import current_user
from concurrent.futures import ThreadPoolExecutor
from app.services.workspace import Workspace


def test_persistence_and_decision(tmp_path):
    store = Workspace(tmp_path)
    store.create("one", "회의")
    assert not store.decide("one", "approved")
    store.finish("one", {"action_items": [{"description": "검토"}]})
    assert store.decide("one", "approved")
    assert not store.decide("one", "rejected")
    reloaded = Workspace(tmp_path).list()[0]
    assert reloaded["status"] == "approved"
    assert reloaded["summary"]["action_items"][0]["description"] == "검토"


def test_concurrent_approval_only_once(tmp_path):
    store = Workspace(tmp_path)
    store.create("one", "회의")
    store.finish("one", {})
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: store.decide("one", "approved"), range(4)))
    assert sum(results) == 1


def test_restart_marks_only_unfinished_jobs_failed(tmp_path):
    store = Workspace(tmp_path)
    store.create("one", "진행 중")
    store.create("two", "검토 중")
    store.finish("two", {})
    store.recover()
    states = {j["id"]: j["status"] for j in store.list()}
    assert states == {"one": "failed", "two": "review"}


def test_decision_api_rejects_duplicates_and_invalid_values(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.workspace import router
    app = FastAPI()
    app.state.workspace = Workspace(tmp_path)
    app.include_router(router)
    app.dependency_overrides[current_user] = lambda: None  # auth covered in test_auth.py
    app.state.workspace.create("one", "회의")
    app.state.workspace.finish("one", {})
    with TestClient(app) as client:
        assert client.get("/workspace/jobs").json()[0]["status"] == "review"
        assert client.post("/workspace/jobs/one/decision", json={"status": "unknown"}).status_code == 422
        assert client.post("/workspace/jobs/one/decision", json={"status": "approved"}).status_code == 200
        assert client.post("/workspace/jobs/one/decision", json={"status": "approved"}).status_code == 409
        assert client.post("/workspace/jobs/missing/decision", json={"status": "rejected"}).status_code == 409


def test_database_uses_wal_for_backups(tmp_path):
    from app.services.workspace import Workspace
    store = Workspace(tmp_path)
    with store.connect() as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
