import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.analysis import OrchestratorOutput
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.routers import upload
from app.routers.workspace import router
from app.services import retention
from app.services.workspace import JobBusyError, Workspace
from app.storage.local import LocalStorage

JOB = "0123456789abcdef0123456789abcdef"
OTHER = "fedcba9876543210fedcba9876543210"


def _files(base, job_id, meeting="m"):
    folder = base / meeting
    folder.mkdir(exist_ok=True)
    for suffix in (".wav", ".json", ".summary.json", ".analysis.json"):
        (folder / f"{job_id}{suffix}").write_text("x")


def _pipeline_mocks(monkeypatch, text):
    transcript = TranscriptResult(meetingId="m", language="ko", duration=60, backend="test", full_text=text,
                                  segments=[TranscriptSegment(start=0, end=60, text=text)])
    analysis = OrchestratorOutput(meeting_id="m", topics=[], decisions=["보고서 검토"],
                                  action_items=[{"description": "보고서 검토"}], participants_mentioned=[],
                                  summary_ko="요약", summary_en="Summary", confidence=.9, routing=[])
    monkeypatch.setenv("WORKSPACE_MODE", "standalone")
    monkeypatch.setattr(upload, "transcribe", AsyncMock(return_value=transcript))
    monkeypatch.setattr(upload, "analyse", AsyncMock(return_value=analysis))
    for name in ("save_guard_report", "save_analysis", "save_summary"):
        monkeypatch.setattr(upload, name, AsyncMock())
    save_transcript = AsyncMock()
    monkeypatch.setattr(upload, "save_transcript", save_transcript)
    return save_transcript


def test_pipeline_masks_citations_and_discards_raw(tmp_path, monkeypatch):
    monkeypatch.delenv("RETAIN_RAW_RECORDINGS", raising=False)
    save_transcript = _pipeline_mocks(monkeypatch, "보고서 검토 test@example.com 으로 전달")
    store = Workspace(tmp_path)
    store.create(JOB, "회의")
    audio = tmp_path / "m" / f"{JOB}.wav"
    audio.parent.mkdir()
    audio.write_bytes(b"RIFF")
    asyncio.run(upload._run_stt_and_guard(audio, f"m/{JOB}.wav", "m", tmp_path))
    summary = store.list()[0]["summary"]
    quoted = summary["action_items"][0]["citation_text"] + summary["decisions"][0]["citation_text"]
    assert "보고서 검토" in quoted
    assert "test@example.com" not in str(summary)
    assert not audio.exists()
    save_transcript.assert_not_called()


def test_pipeline_failure_still_discards_audio(tmp_path, monkeypatch):
    monkeypatch.delenv("RETAIN_RAW_RECORDINGS", raising=False)
    monkeypatch.setattr(upload, "transcribe", AsyncMock(side_effect=RuntimeError("boom")))
    store = Workspace(tmp_path)
    store.create(JOB, "회의")
    audio = tmp_path / f"{JOB}.wav"
    audio.write_bytes(b"RIFF")
    asyncio.run(upload._run_stt_and_guard(audio, f"m/{JOB}.wav", "m", tmp_path))
    assert store.list()[0]["status"] == "failed"
    assert not audio.exists()


def test_retain_flag_keeps_raw(tmp_path, monkeypatch):
    monkeypatch.setenv("RETAIN_RAW_RECORDINGS", "true")
    save_transcript = _pipeline_mocks(monkeypatch, "보고서 검토")
    Workspace(tmp_path).create(JOB, "회의")
    audio = tmp_path / f"{JOB}.wav"
    audio.write_bytes(b"RIFF")
    asyncio.run(upload._run_stt_and_guard(audio, f"m/{JOB}.wav", "m", tmp_path))
    assert audio.exists()
    save_transcript.assert_awaited_once()


def _client(tmp_path):
    app = FastAPI()
    app.state.workspace = Workspace(tmp_path)
    app.state.storage = LocalStorage(tmp_path)
    app.include_router(router)
    return app, TestClient(app)


def test_delete_api_removes_row_and_only_that_jobs_files(tmp_path):
    app, client = _client(tmp_path)
    for job in (JOB, OTHER):
        app.state.workspace.create(job, "회의")
        app.state.workspace.finish(job, {})
        _files(tmp_path, job)
    assert client.delete(f"/workspace/jobs/{JOB}").status_code == 200
    assert [j["id"] for j in app.state.workspace.list()] == [OTHER]
    assert not list(tmp_path.glob(f"*/{JOB}.*"))
    assert len(list(tmp_path.glob(f"*/{OTHER}.*"))) == 4
    assert client.delete(f"/workspace/jobs/{JOB}").status_code == 404


def test_delete_api_refuses_processing_and_bad_ids(tmp_path):
    app, client = _client(tmp_path)
    app.state.workspace.create(JOB, "회의")
    _files(tmp_path, JOB)
    assert client.delete(f"/workspace/jobs/{JOB}").status_code == 409
    assert len(list(tmp_path.glob(f"*/{JOB}.*"))) == 4
    assert client.delete("/workspace/jobs/..").status_code in (404, 405)
    assert client.delete("/workspace/jobs/*").status_code == 404


def test_storage_rejects_glob_or_traversal_ids(tmp_path):
    with pytest.raises(ValueError):
        LocalStorage(tmp_path).delete_job_files("*")
    with pytest.raises(JobBusyError):
        store = Workspace(tmp_path)
        store.create(JOB, "t")
        store.delete(JOB)


def test_purge_expired_respects_retention_days(tmp_path, monkeypatch):
    store, storage = Workspace(tmp_path), LocalStorage(tmp_path)
    for job in (JOB, OTHER):
        store.create(job, "회의")
        store.finish(job, {})
        _files(tmp_path, job)
    with store.connect() as db:
        db.execute("UPDATE jobs SET created_at=datetime('now','-40 days') WHERE id=?", (JOB,))
    monkeypatch.delenv("MEETING_RETENTION_DAYS", raising=False)
    assert asyncio.run(retention.purge_expired(store, storage)) == 0
    monkeypatch.setenv("MEETING_RETENTION_DAYS", "30")
    assert asyncio.run(retention.purge_expired(store, storage)) == 1
    assert [j["id"] for j in store.list()] == [OTHER]
    assert not list(tmp_path.glob(f"*/{JOB}.*"))
