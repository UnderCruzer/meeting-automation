import asyncio
import json

import httpx
import pytest

from app.services import llm, orchestrator
from app.models.transcript import TranscriptResult, TranscriptSegment

_real_client = httpx.AsyncClient


def _mock_gemini(monkeypatch, response_json, status=200):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=response_json)

    monkeypatch.setattr(
        llm.httpx, "AsyncClient",
        lambda **kw: _real_client(transport=httpx.MockTransport(handler), **kw),
    )
    return calls


def _gemini_env(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-only")


def _candidate(text, finish="STOP"):
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}]}


def test_provider_selection(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert llm.provider() == "anthropic"
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert llm.provider() == "gemini"
    assert llm.api_key_env() == "GEMINI_API_KEY"
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert llm.api_key_env() == "ANTHROPIC_API_KEY"
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(RuntimeError):
        llm.provider()


def test_schema_conversion_uppercases_types_and_drops_unknown_keys():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "n": {"type": "number", "minimum": 0, "maximum": 1},
            "tags": {"type": "array", "items": {"type": "string", "enum": ["a", "b"]}},
        },
        "required": ["n"],
    }
    assert llm.to_gemini_schema(schema) == {
        "type": "OBJECT",
        "properties": {
            "n": {"type": "NUMBER", "minimum": 0, "maximum": 1},
            "tags": {"type": "ARRAY", "items": {"type": "STRING", "enum": ["a", "b"]}},
        },
        "required": ["n"],
    }


def test_gemini_structured_request_and_parse(monkeypatch):
    _gemini_env(monkeypatch)
    calls = _mock_gemini(monkeypatch, _candidate('{"drafts": []}'))
    out = asyncio.run(llm.generate_structured(
        prompt="p", system="s", name="t", description="d",
        schema={"type": "object", "properties": {"drafts": {"type": "array", "items": {"type": "string"}}}},
        max_tokens=100,
    ))
    assert out == {"drafts": []}
    req = calls[0]
    assert req.url.path.endswith("/models/gemini-3.8-flash:generateContent")
    assert req.headers["x-goog-api-key"] == "test-only"
    body = json.loads(req.content)
    assert body["systemInstruction"]["parts"][0]["text"] == "s"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseSchema"]["type"] == "OBJECT"


def test_gemini_model_override_and_thought_parts_skipped(monkeypatch):
    _gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    calls = _mock_gemini(monkeypatch, {"candidates": [{"content": {"parts": [
        {"text": "thinking...", "thought": True}, {"text": "답변"}]}, "finishReason": "STOP"}]})
    assert asyncio.run(llm.generate_text(prompt="p", max_tokens=10)) == "답변"
    assert "gemini-3.1-flash-lite" in calls[0].url.path


@pytest.mark.parametrize("payload,status,message", [
    ({"error": {"message": "echo of prompt"}}, 400, "Gemini API error 400"),
    (_candidate('{"a":', "MAX_TOKENS"), 200, "truncated"),
    ({"promptFeedback": {"blockReason": "SAFETY"}}, 200, "SAFETY"),
    (_candidate("not json"), 200, "invalid JSON"),
])
def test_gemini_failures_raise_without_leaking_body(monkeypatch, payload, status, message):
    _gemini_env(monkeypatch)
    _mock_gemini(monkeypatch, payload, status)
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(llm.generate_structured(
            prompt="p", name="t", description="d", schema={"type": "object"}, max_tokens=10))
    assert message in str(exc.value)
    assert "echo of prompt" not in str(exc.value)


def test_missing_key_raises(monkeypatch):
    _gemini_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        asyncio.run(llm.generate_text(prompt="p", max_tokens=10))


def test_orchestrator_sends_only_masked_text_to_gemini(monkeypatch):
    _gemini_env(monkeypatch)
    result = dict(topics=[], decisions=[], action_items=[], participants_mentioned=[],
                  summary_ko="요약", summary_en="Summary", confidence=.8, routing=[])
    calls = _mock_gemini(monkeypatch, _candidate(json.dumps(result, ensure_ascii=False)))
    transcript = TranscriptResult(meetingId="m", language="ko", duration=60, backend="test",
                                  full_text="private@example.com",
                                  segments=[TranscriptSegment(start=0, end=60, text="private@example.com")])
    out = asyncio.run(orchestrator.analyse(transcript, masked_text="[EMAIL] 검토"))
    sent = calls[0].content.decode()
    assert "private@example.com" not in sent
    assert "[EMAIL]" in sent
    assert out.summary_ko == "요약"


def _sequence(monkeypatch, responses):
    """Mock Gemini returning the given (status, json) pairs in order; record calls and sleeps."""
    calls, sleeps = [], []
    queue = list(responses)

    def handler(request):
        calls.append(request)
        status, payload, headers = queue.pop(0)
        return httpx.Response(status, json=payload, headers=headers)

    monkeypatch.setattr(llm.httpx, "AsyncClient",
                        lambda **kw: _real_client(transport=httpx.MockTransport(handler), **kw))

    async def fake_sleep(seconds):
        sleeps.append(seconds)
    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)
    return calls, sleeps


def test_gemini_retries_overload_then_succeeds(monkeypatch):
    _gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_MAX_ATTEMPTS", "3")
    busy = (503, {"error": {"message": "overloaded"}}, {})
    calls, sleeps = _sequence(monkeypatch, [busy, (429, {}, {"Retry-After": "7"}), (200, _candidate("ok"), {})])
    assert asyncio.run(llm.generate_text(prompt="p", max_tokens=10)) == "ok"
    assert len(calls) == 3 and sleeps[1] == 7.0


def test_gemini_falls_back_to_next_model(monkeypatch):
    _gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-backup")
    busy = (503, {}, {})
    calls, _ = _sequence(monkeypatch, [busy, busy, (200, _candidate("from backup"), {})])
    assert asyncio.run(llm.generate_text(prompt="p", max_tokens=10)) == "from backup"
    assert "gemini-backup" in calls[2].url.path


def test_gemini_gives_up_with_unavailable(monkeypatch):
    _gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "")
    _sequence(monkeypatch, [(503, {}, {}), (503, {}, {})])
    with pytest.raises(llm.LLMUnavailable):
        asyncio.run(llm.generate_text(prompt="p", max_tokens=10))


def test_gemini_client_errors_are_not_retried(monkeypatch):
    _gemini_env(monkeypatch)
    calls, _ = _sequence(monkeypatch, [(400, {"error": {"message": "bad"}}, {})])
    with pytest.raises(RuntimeError, match="400"):
        asyncio.run(llm.generate_text(prompt="p", max_tokens=10))
    assert len(calls) == 1
