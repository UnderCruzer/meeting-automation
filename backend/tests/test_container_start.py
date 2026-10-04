"""deploy/container/start.py — Litestream backup restore, secrets isolation and alerts (#85)."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "container_start", Path(__file__).resolve().parents[2] / "deploy" / "container" / "start.py")
start = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(start)

KEYS = {"LITESTREAM_ACCESS_KEY_ID": "test-key-id", "LITESTREAM_SECRET_ACCESS_KEY": "test-secret"}


@pytest.fixture
def backup_env(monkeypatch, tmp_path):
    for name in ("LITESTREAM_ENDPOINT", "LITESTREAM_REGION", "LITESTREAM_PATH", "LITESTREAM_RETENTION",
                 "SLACK_BOT_TOKEN", "MONITOR_ALERT_CHANNEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "recordings"))
    monkeypatch.setenv("LITESTREAM_BUCKET", "team-backup")
    for key, value in KEYS.items():
        monkeypatch.setenv(key, value)
    return tmp_path


def test_backup_needs_bucket_and_both_keys(backup_env, monkeypatch):
    assert start.backup_enabled()
    monkeypatch.delenv("LITESTREAM_SECRET_ACCESS_KEY")
    assert not start.backup_enabled()


def test_config_has_replica_but_no_secrets(backup_env, monkeypatch):
    monkeypatch.setenv("LITESTREAM_ENDPOINT", "https://s3.us-west-004.backblazeb2.com")
    monkeypatch.setenv("LITESTREAM_REGION", "us-west-004")
    text = Path(start.write_backup_config(str(backup_env / "ls.yml"))).read_text()
    assert f'- path: "{backup_env}/recordings/workspace.sqlite3"' in text
    assert 'bucket: "team-backup"' in text and 'path: "meeting-automation"' in text
    assert 'endpoint: "https://s3.us-west-004.backblazeb2.com"' in text and 'region: "us-west-004"' in text
    assert 'retention: "168h"' in text
    assert "test-secret" not in text and "test-key-id" not in text   # Litestream reads them from the env


def test_backup_keys_never_reach_web_or_bot(backup_env, monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "k")
    bot = start._bot_env()
    api = start._env_without(start._BACKUP_SECRETS)
    assert not set(KEYS) & set(bot) and not set(KEYS) & set(api)


def _run(monkeypatch, returncode=0, creates=False):
    calls = []

    def fake_run(command, timeout):
        calls.append(command)
        if creates:
            Path(command[-1]).write_bytes(b"SQLite format 3\x00")
        return subprocess.CompletedProcess(command, returncode)

    monkeypatch.setattr(start.subprocess, "run", fake_run)
    return calls


def test_fresh_container_restores_from_backup(backup_env, monkeypatch):
    calls = _run(monkeypatch, creates=True)
    assert start.restore_database("/tmp/ls.yml") == "restored"
    assert calls[0][:4] == ["litestream", "restore", "-config", "/tmp/ls.yml"]
    assert "-if-replica-exists" in calls[0] and "-if-db-not-exists" in calls[0]


def test_first_run_without_backup_starts_fresh(backup_env, monkeypatch):
    _run(monkeypatch)
    assert start.restore_database("/tmp/ls.yml") == "fresh"


def test_existing_database_is_kept(backup_env, monkeypatch):
    calls = _run(monkeypatch)
    db = backup_env / "recordings" / "workspace.sqlite3"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"x")
    assert start.restore_database("/tmp/ls.yml") == "kept" and calls == []


def test_failed_restore_refuses_to_start_and_alerts(backup_env, monkeypatch):
    _run(monkeypatch, returncode=1)
    sent = []
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-only")
    monkeypatch.setenv("MONITOR_ALERT_CHANNEL", "C0ADMIN")

    class Response:
        def close(self):
            pass

    def fake_urlopen(request, timeout):
        sent.append(json.loads(request.data))
        return Response()

    monkeypatch.setattr(start.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="refusing to start"):
        start.restore_database("/tmp/ls.yml")
    assert sent[0]["channel"] == "C0ADMIN" and "복원하지 못해" in sent[0]["text"]


def test_crash_loop_alerts_once(monkeypatch):
    alerts, started = [], []

    class Dead:
        returncode = 1

        def poll(self):
            return 1

    monkeypatch.setattr(start.subprocess, "Popen", lambda *a, **k: started.append(1) or Dead())
    monkeypatch.setattr(start, "alert", alerts.append)
    proc = start.Supervised("litestream", ["litestream"], alert_text="backup down")
    for now in (0, 10, 30, 70, 150, 310):
        proc.tick(now)
    assert len(started) >= 4 and alerts == ["backup down"]
