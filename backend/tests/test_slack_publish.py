import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.auth import current_user
from app.routers.workspace import router
from app.services import regional_delivery, slack_publish, write_queue
from app.services.audit import AuditLog
from app.services.workspace import Workspace
from app.storage.local import LocalStorage

JOB = "0123456789abcdef0123456789abcdef"
SUMMARY = {"meeting_id": "m", "summary_ko": "출시 일정 확정", "summary_en": "Launch date fixed",
           "decisions": [{"text": "10월 출시"}],
           "action_items": [{"description": "릴리스 노트 작성", "assignee": "김민수", "due_date": "10/10"}],
           "quality_flags": [], "quality_ok": True}
WORK_HOURS_KST = datetime(2026, 10, 1, 2, 0, tzinfo=timezone.utc)   # Thu 11:00 KST
NIGHT_KST = datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc)       # Thu 22:00 KST
_real_client = httpx.AsyncClient


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-only")
    monkeypatch.setenv("SLACK_CHANNEL_APAC", "C0APAC123")
    monkeypatch.delenv("WORKSPACE_TIMEZONES", raising=False)
    monkeypatch.setenv("DEFAULT_TIMEZONE", "Asia/Seoul")
    while not write_queue._queue.empty():
        write_queue._queue.get_nowait()
    posts = []

    def slack(request):
        posts.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "ts": "1.2", "channel": "C0APAC123"})

    monkeypatch.setattr(regional_delivery.httpx, "AsyncClient",
                        lambda **kw: _real_client(transport=httpx.MockTransport(slack), **kw))
    app = FastAPI()
    app.state.workspace = Workspace(tmp_path)
    app.state.storage = LocalStorage(tmp_path)
    app.state.audit = AuditLog(tmp_path)
    app.include_router(router)
    app.dependency_overrides[current_user] = lambda: None
    app.state.workspace.create(JOB, "출시 회의")
    app.state.workspace.finish(JOB, SUMMARY)
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / f"{JOB}.json").write_text("{}")
    return app, posts


def _at(monkeypatch, now):
    real = slack_publish.resolve_send_time
    monkeypatch.setattr(slack_publish, "resolve_send_time", lambda tzs: real(tzs, now_utc=now))


def _drain():
    task = write_queue._queue.get_nowait()
    asyncio.run(write_queue._dispatch(task))
    return task


def test_work_hours_approval_posts_brief_to_region_channel(env, monkeypatch):
    app, posts = env
    _at(monkeypatch, WORK_HOURS_KST)
    client = TestClient(app)
    res = client.post(f"/workspace/jobs/{JOB}/decision", json={"status": "approved"})
    assert res.json()["publish"]["publish_status"] == "queued"
    task = _drain()
    assert task.meeting_id == "m"  # write-queue audit next to the job's files
    assert posts[0]["channel"] == "C0APAC123"  # channel ID passed as-is (no "#")
    assert "릴리스 노트 작성" in posts[0]["text"] and "김민수" in posts[0]["text"]
    job = app.state.workspace.get(JOB)
    assert job["publish_status"] == "sent" and job["publish_channel"] == "C0APAC123"
    assert [e["action"] for e in app.state.audit.recent()][:2] == ["publish", "publish_request"]


def test_night_approval_is_scheduled_unless_publish_now(env, monkeypatch):
    app, posts = env
    _at(monkeypatch, NIGHT_KST)
    client = TestClient(app)
    publish = client.post(f"/workspace/jobs/{JOB}/decision", json={"status": "approved"}).json()["publish"]
    assert publish["publish_status"] == "scheduled"
    assert publish["publish_at"].startswith("2026-10-02T00:00")  # Fri 09:00 KST
    assert write_queue._queue.empty()  # waiting in the scheduler, not sent
    assert app.state.workspace.get(JOB)["publish_status"] == "scheduled"
    assert client.post(f"/workspace/jobs/{JOB}/publish", json={"now": True}).status_code == 409  # already pending
    for pending in list(write_queue._delayed):
        pending.cancel()


def test_publish_now_overrides_schedule(env, monkeypatch):
    app, posts = env
    _at(monkeypatch, NIGHT_KST)
    res = TestClient(app).post(f"/workspace/jobs/{JOB}/decision", json={"status": "approved", "publish_now": True})
    assert res.json()["publish"]["publish_status"] == "queued"
    _drain()
    assert len(posts) == 1


def test_deleted_meeting_is_not_posted(env, monkeypatch):
    app, posts = env
    _at(monkeypatch, WORK_HOURS_KST)
    client = TestClient(app)
    client.post(f"/workspace/jobs/{JOB}/decision", json={"status": "approved"})
    assert client.delete(f"/workspace/jobs/{JOB}").status_code == 200
    _drain()
    assert posts == []


def test_failure_marks_failed_and_allows_retry(env, monkeypatch):
    app, posts = env
    _at(monkeypatch, WORK_HOURS_KST)

    def broken(request):
        return httpx.Response(200, json={"ok": False, "error": "not_in_channel"})
    monkeypatch.setattr(regional_delivery.httpx, "AsyncClient",
                        lambda **kw: _real_client(transport=httpx.MockTransport(broken), **kw))
    async def no_sleep(_): return None
    monkeypatch.setattr(write_queue.asyncio, "sleep", no_sleep)
    async def no_alert(**_): return None
    import app.services.alert as alert
    monkeypatch.setattr(alert, "send_failure_alert", no_alert)
    client = TestClient(app)
    client.post(f"/workspace/jobs/{JOB}/decision", json={"status": "approved"})
    _drain()
    assert app.state.workspace.get(JOB)["publish_status"] == "failed"
    assert client.post(f"/workspace/jobs/{JOB}/publish", json={"now": True}).json()["publish_status"] == "queued"


def test_restart_marks_pending_posts_failed(env):
    app, _ = env
    app.state.workspace.set_publish(JOB, "scheduled", at="2026-10-02T00:00:00+00:00")
    app.state.workspace.recover()
    job = app.state.workspace.get(JOB)
    assert job["publish_status"] == "failed" and "재시작" in job["publish_error"]


def test_without_token_approval_skips_slack(env, monkeypatch):
    app, posts = env
    monkeypatch.delenv("SLACK_BOT_TOKEN")
    client = TestClient(app)
    assert client.get("/workspace/config").json() == {"slackPublishing": False}
    assert "publish" not in client.post(f"/workspace/jobs/{JOB}/decision", json={"status": "approved"}).json()
    assert client.post(f"/workspace/jobs/{JOB}/publish", json={"now": True}).status_code == 409
    assert write_queue._queue.empty()


def test_na_team_gets_english_brief(env, monkeypatch):
    app, posts = env
    monkeypatch.setenv("WORKSPACE_TIMEZONES", "America/New_York")
    monkeypatch.setenv("SLACK_CHANNEL_NA", "C0NA456")
    _at(monkeypatch, datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc))  # 11:00 ET
    TestClient(app).post(f"/workspace/jobs/{JOB}/decision", json={"status": "approved"})
    _drain()
    assert posts[0]["channel"] == "C0NA456"
    assert "Launch date fixed" in posts[0]["text"] and "Action items" in posts[0]["text"]


def test_delay_parsing():
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert write_queue._delay_seconds("", now) == 0
    assert write_queue._delay_seconds("cancelled", now) == 0
    assert write_queue._delay_seconds("2026-09-30T00:00:00+00:00", now) == 0
    assert write_queue._delay_seconds("2026-10-01T00:01:00+00:00", now) == 60
