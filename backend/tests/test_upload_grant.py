import io
import json
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import upload
from app.services.accounts import Accounts
from app.services.audit import AuditLog
from app.services.workspace import Workspace
from app.storage.local import LocalStorage

KEY = "internal-test-key"


def _wav():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\0\0" * 16000)
    return buf.getvalue()


def _meta(meeting_id):
    return json.dumps({"meetingId": meeting_id, "title": "주간 회의", "startTime": "2026-10-01T06:00:00Z",
                       "endTime": "2026-10-01T07:00:00Z"})


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_MODE", "standalone")
    monkeypatch.setenv("BACKEND_API_KEY", KEY)
    monkeypatch.setattr(upload, "_run_stt_and_guard", lambda *a, **k: None)
    app = FastAPI()
    app.state.storage = LocalStorage(tmp_path)
    app.state.workspace = Workspace(tmp_path)
    app.state.accounts = Accounts(tmp_path)
    app.state.audit = AuditLog(tmp_path)
    app.include_router(upload.router)
    return app, TestClient(app)


def _post(client, meeting, headers):
    return client.post("/upload", headers=headers, data={"metadata": _meta(meeting)},
                       files={"audio": ("a.wav", _wav(), "audio/wav")})


def test_signed_link_upload_records_slack_actor(client):
    app, c = client
    res = _post(c, "ics:weekly-1:2026-10-01T06:00:00.000Z", {
        "X-API-Key": KEY, "X-Upload-Actor": "slack:U0123ABC",
        "X-Upload-Meeting": "ics%3Aweekly-1%3A2026-10-01T06%3A00%3A00.000Z"})
    assert res.status_code == 200
    assert app.state.workspace.list()[0]["uploaded_by"] == "slack:U0123ABC"
    assert app.state.audit.recent()[0]["username"] == "slack:U0123ABC"


def test_signed_link_cannot_upload_other_meetings(client):
    _, c = client
    res = _post(c, "another-meeting", {"X-API-Key": KEY, "X-Upload-Actor": "slack:U0123ABC",
                                       "X-Upload-Meeting": "ics%3Aweekly-1"})
    assert res.status_code == 403


@pytest.mark.parametrize("headers", [
    {"X-Upload-Actor": "slack:U0123ABC", "X-Upload-Meeting": "m"},                       # no API key
    {"X-API-Key": "wrong", "X-Upload-Actor": "slack:U0123ABC", "X-Upload-Meeting": "m"},  # wrong key
    {"X-API-Key": KEY, "X-Upload-Actor": "admin", "X-Upload-Meeting": "m"},              # not a Slack actor
    {"X-API-Key": KEY, "X-Upload-Actor": "slack:U0123ABC"},                              # no meeting lock
    {"X-API-Key": KEY},                                                                   # no session at all
])
def test_untrusted_or_incomplete_actor_is_rejected(client, headers):
    _, c = client
    assert _post(c, "m", headers).status_code == 401
