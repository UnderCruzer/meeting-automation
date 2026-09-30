import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services import orchestrator


def test_masked_input_not_replaced_with_raw_diarized_transcript(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only")
    result = dict(topics=[], decisions=[], action_items=[], participants_mentioned=[], summary_ko="요약", summary_en="Summary", confidence=.8, routing=[])
    create = AsyncMock(return_value=SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=result)]))
    monkeypatch.setattr(orchestrator.anthropic, "AsyncAnthropic", lambda **_: SimpleNamespace(messages=SimpleNamespace(create=create)))
    transcript = TranscriptResult(meetingId="meeting", language="ko", duration=60, backend="test", full_text="private@example.com", segments=[
        TranscriptSegment(start=0,end=20,text="private@example.com",speaker="A"),
        TranscriptSegment(start=21,end=60,text="검토합니다",speaker="B"),
    ])
    asyncio.run(orchestrator.analyse(transcript, masked_text="[EMAIL] 검토합니다"))
    sent = create.call_args.kwargs["messages"][0]["content"]
    assert "private@example.com" not in sent
    assert "[EMAIL] 검토합니다" in sent
