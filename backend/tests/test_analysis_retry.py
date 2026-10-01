import asyncio
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.analysis import OrchestratorOutput
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.routers import upload
from app.routers.auth import current_user
from app.routers.workspace import router
from app.services.audit import AuditLog
from app.services.llm import LLMUnavailable
from app.services.workspace import Workspace
from app.storage.local import LocalStorage

JOB = "0123456789abcdef0123456789abcdef"
TEXT = "김민수 팀장이 보고서 검토 test@example.com"


def _setup(tmp_path, monkeypatch, analyse):
    monkeypatch.setenv("WORKSPACE_MODE", "standalone")
    monkeypatch.delenv("RETAIN_RAW_RECORDINGS", raising=False)
    transcript = TranscriptResult(meetingId="m", language="ko", duration=60, backend="test", full_text=TEXT,
                                  segments=[TranscriptSegment(start=0, end=60, text=TEXT)])
    monkeypatch.setattr(upload, "transcribe", AsyncMock(return_value=transcript))
    monkeypatch.setattr(upload, "analyse", analyse)
    for name in ("save_guard_report", "save_analysis", "save_summary"):
        monkeypatch.setattr(upload, name, AsyncMock())
    store = Workspace(tmp_path)
    store.create(JOB, "회의")
    (tmp_path / "m").mkdir()
    audio = tmp_path / "m" / f"{JOB}.wav"
    audio.write_bytes(b"RIFF")
    asyncio.run(upload._run_stt_and_guard(audio, f"m/{JOB}.wav", "m", tmp_path))
    return store, audio


def _ok_analysis(t, masked_text):
    import re
    token = re.search(r"\[PERSON_\d+\]", masked_text).group(0)
    return OrchestratorOutput(meeting_id="m", topics=[], decisions=[],
                              action_items=[{"description": "보고서 검토", "assignee": token}],
                              participants_mentioned=[], summary_ko=f"{token} 검토", summary_en="",
                              confidence=.9, routing=[])


def test_llm_overload_is_retryable_without_reupload(tmp_path, monkeypatch):
    analyse = AsyncMock(side_effect=LLMUnavailable("busy"))
    store, audio = _setup(tmp_path, monkeypatch, analyse)
    job = store.get(JOB)
    assert (job["status"], job["error_code"], job["can_retry"]) == ("failed", "LLM_BUSY", True)
    assert not audio.exists()  # raw audio still removed

    app = FastAPI()
    app.state.workspace, app.state.storage, app.state.audit = store, LocalStorage(tmp_path), AuditLog(tmp_path)
    app.include_router(router)
    app.dependency_overrides[current_user] = lambda: None
    analyse.side_effect = _ok_analysis
    client = TestClient(app)
    assert client.post(f"/workspace/jobs/{JOB}/retry").status_code == 200  # runs in background task
    job = store.get(JOB)
    assert job["status"] == "review" and job["error_code"] is None and job["can_retry"] is False
    assert job["summary"]["action_items"][0]["assignee"] == "김민수"
    # Retry used only the stored masked text
    sent = analyse.call_args.kwargs["masked_text"]
    assert "김민수" not in sent and "test@example.com" not in sent
    assert client.post(f"/workspace/jobs/{JOB}/retry").status_code == 409
    assert app.state.audit.recent()[0]["action"] == "retry"


def test_retry_payload_holds_no_raw_text(tmp_path, monkeypatch):
    store, _ = _setup(tmp_path, monkeypatch, AsyncMock(side_effect=RuntimeError("bad output")))
    with store.connect() as db:
        payload = db.execute("SELECT retry_payload FROM jobs").fetchone()[0]
    assert "test@example.com" not in payload
    assert store.get(JOB)["error_code"] == "ANALYSIS_FAILED"
    assert "retry_payload" not in store.get(JOB)


def test_stt_failure_is_not_retryable(tmp_path, monkeypatch):
    monkeypatch.setattr(upload, "transcribe", AsyncMock(side_effect=RuntimeError("groq down")))
    store = Workspace(tmp_path)
    store.create(JOB, "회의")
    asyncio.run(upload._run_stt_and_guard(tmp_path / "a.wav", f"m/{JOB}.wav", "m", tmp_path))
    job = store.get(JOB)
    assert (job["error_code"], job["can_retry"]) == ("STT_FAILED", False)


def test_silent_recording_reports_no_speech(tmp_path, monkeypatch):
    silent = TranscriptResult(meetingId="m", language="ko", duration=5, backend="test", full_text="", segments=[])
    monkeypatch.setattr(upload, "transcribe", AsyncMock(return_value=silent))
    monkeypatch.setattr(upload, "save_guard_report", AsyncMock())
    store = Workspace(tmp_path)
    store.create(JOB, "회의")
    asyncio.run(upload._run_stt_and_guard(tmp_path / "a.wav", f"m/{JOB}.wav", "m", tmp_path))
    assert store.get(JOB)["error_code"] == "NO_SPEECH"


def test_restart_reports_restarted(tmp_path):
    store = Workspace(tmp_path)
    store.create(JOB, "회의")
    store.recover()
    assert store.get(JOB)["error_code"] == "RESTARTED"
