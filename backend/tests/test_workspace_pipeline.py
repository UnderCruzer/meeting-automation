import asyncio
from unittest.mock import AsyncMock
from app.routers import upload
from app.services.workspace import Workspace
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.models.analysis import OrchestratorOutput


def test_standalone_pipeline_skips_external_delivery(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_MODE", "standalone")
    store = Workspace(tmp_path)
    store.create("abc", "회의")
    transcript = TranscriptResult(meetingId="meeting", language="ko", duration=60, segments=[TranscriptSegment(start=0,end=60,text="이메일 test@example.com 검토")], full_text="이메일 test@example.com 검토", backend="test")
    analysis = OrchestratorOutput(meeting_id="meeting", topics=[], decisions=[], action_items=[], participants_mentioned=[], summary_ko="검토", summary_en="Review", confidence=.8, routing=["slack"])
    monkeypatch.setattr(upload,"transcribe",AsyncMock(return_value=transcript))
    analyse = AsyncMock(return_value=analysis)
    monkeypatch.setattr(upload,"analyse",analyse)
    for name in ("save_transcript","save_guard_report","save_analysis","save_summary"):
        monkeypatch.setattr(upload,name,AsyncMock())
    delivery = AsyncMock()
    monkeypatch.setattr(upload,"send_review_message",delivery)
    retrieval = AsyncMock()
    monkeypatch.setattr(upload,"retrieve_context",retrieval)
    asyncio.run(upload._run_stt_and_guard(tmp_path/"abc.wav","meeting/abc.wav","meeting",tmp_path))
    assert store.list()[0]["status"] == "review"
    assert "test@example.com" not in analyse.call_args.kwargs["masked_text"]
    delivery.assert_not_called()
    retrieval.assert_not_called()


def test_pipeline_failure_is_visible(tmp_path, monkeypatch):
    store = Workspace(tmp_path)
    store.create("abc", "회의")
    monkeypatch.setattr(upload,"transcribe",AsyncMock(side_effect=RuntimeError("private provider error")))
    asyncio.run(upload._run_stt_and_guard(tmp_path/"abc.wav","meeting/abc.wav","meeting",tmp_path))
    assert store.list()[0]["status"] == "failed"
    assert "private provider error" not in str(store.list())
