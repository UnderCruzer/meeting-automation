from __future__ import annotations
"""
LLM provider abstraction — Gemini (REST) or Claude (anthropic SDK).

LLM_PROVIDER=gemini|anthropic selects the provider. When unset, Gemini is used
if GEMINI_API_KEY is present, otherwise Claude.

Every caller must pass PII-masked text; this module does not mask.
"""
import asyncio
import json
import logging
import os
import random

import anthropic
import httpx

logger = logging.getLogger(__name__)

_CLAUDE_MODEL = "claude-sonnet-4-6"
_GEMINI_DEFAULT_MODEL = "gemini-3.8-flash"
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_GEMINI_TIMEOUT = 180.0
_GEMINI_DEFAULT_FALLBACKS = "gemini-3.1-flash-lite"
# Overload / rate-limit / transient server errors: worth retrying.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_BACKOFF_SECONDS = 30.0


class LLMUnavailable(RuntimeError):
    """The provider stayed overloaded or rate-limited after retries (try again later)."""

# JSON Schema keys that Gemini's responseSchema (OpenAPI subset) accepts.
_GEMINI_SCHEMA_KEYS = {
    "type", "description", "enum", "properties", "required", "items",
    "minimum", "maximum", "minItems", "maxItems", "nullable", "format",
}


def provider() -> str:
    explicit = os.getenv("LLM_PROVIDER", "").strip().lower()
    if explicit:
        if explicit not in ("gemini", "anthropic"):
            raise RuntimeError(f"Unsupported LLM_PROVIDER: {explicit}")
        return explicit
    return "gemini" if os.getenv("GEMINI_API_KEY") else "anthropic"


def api_key_env() -> str:
    """Env var name holding the key for the active provider."""
    return "GEMINI_API_KEY" if provider() == "gemini" else "ANTHROPIC_API_KEY"


def _require_key() -> str:
    name = api_key_env()
    key = os.getenv(name)
    if not key:
        raise RuntimeError(f"{name} not set")
    return key


async def generate_structured(
    *,
    prompt: str,
    name: str,
    description: str,
    schema: dict,
    max_tokens: int,
    system: str | None = None,
) -> dict:
    """Return a dict matching `schema` (JSON Schema) for the given prompt."""
    key = _require_key()
    if provider() == "gemini":
        text = await _gemini(
            key, prompt, system, max_tokens,
            {"responseMimeType": "application/json", "responseSchema": to_gemini_schema(schema)},
        )
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Gemini returned invalid JSON") from exc

    client = anthropic.AsyncAnthropic(api_key=key)
    kwargs = {"system": system} if system else {}
    response = await client.messages.create(
        model=_CLAUDE_MODEL,
        max_tokens=max_tokens,
        tools=[{"name": name, "description": description, "input_schema": schema}],
        tool_choice={"type": "tool", "name": name},
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    tool_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_block is None:
        raise RuntimeError(f"Claude did not return a {name} tool_use block")
    return tool_block.input


async def generate_text(*, prompt: str, max_tokens: int) -> str:
    key = _require_key()
    if provider() == "gemini":
        return await _gemini(key, prompt, None, max_tokens, {})

    client = anthropic.AsyncAnthropic(api_key=key)
    response = await client.messages.create(
        model=_CLAUDE_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def to_gemini_schema(schema: dict) -> dict:
    """Convert a JSON Schema dict to Gemini's responseSchema format."""
    out: dict = {}
    for key, value in schema.items():
        if key not in _GEMINI_SCHEMA_KEYS:
            continue
        if key == "type":
            out[key] = value.upper()
        elif key == "properties":
            out[key] = {k: to_gemini_schema(v) for k, v in value.items()}
        elif key == "items":
            out[key] = to_gemini_schema(value)
        else:
            out[key] = value
    return out


def _gemini_models() -> list[str]:
    primary = os.getenv("GEMINI_MODEL", _GEMINI_DEFAULT_MODEL)
    fallbacks = os.getenv("GEMINI_FALLBACK_MODELS", _GEMINI_DEFAULT_FALLBACKS)
    models = [primary] + [m.strip() for m in fallbacks.split(",") if m.strip()]
    return list(dict.fromkeys(models))  # de-duplicate, keep order


def _retry_after(res: httpx.Response) -> float | None:
    try:
        return min(float(res.headers.get("retry-after", "")), _MAX_BACKOFF_SECONDS)
    except ValueError:
        return None


async def _gemini(
    key: str, prompt: str, system: str | None, max_tokens: int, extra_config: dict,
) -> str:
    """Call Gemini with retries on overload, then fall back to the next model."""
    body: dict = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        # Thinking models spend output tokens on reasoning; leave headroom.
        "generationConfig": {"maxOutputTokens": max_tokens * 2, **extra_config},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    attempts = max(1, int(os.getenv("GEMINI_MAX_ATTEMPTS", "4")))

    last_status: int | str = "unknown"
    for model in _gemini_models():
        for attempt in range(1, attempts + 1):
            wait: float | None = None
            try:
                async with httpx.AsyncClient(timeout=_GEMINI_TIMEOUT) as client:
                    res = await client.post(
                        _GEMINI_URL.format(model=model), headers={"x-goog-api-key": key}, json=body,
                    )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_status = type(exc).__name__
            else:
                if res.status_code == 200:
                    return _gemini_text(res.json())
                if res.status_code not in _RETRYABLE_STATUS:
                    # Response body may echo the prompt; report status only.
                    raise RuntimeError(f"Gemini API error {res.status_code}")
                last_status = res.status_code
                wait = _retry_after(res)
            logger.warning("[LLM] Gemini %s attempt %d/%d failed (%s)", model, attempt, attempts, last_status)
            if attempt < attempts:
                await asyncio.sleep(wait if wait is not None else min(2 ** attempt, _MAX_BACKOFF_SECONDS) + random.random())
    raise LLMUnavailable(f"Gemini unavailable after retries ({last_status})")


def _gemini_text(data: dict) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
        raise RuntimeError(f"Gemini returned no output ({reason})")
    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    finish = candidate.get("finishReason", "")
    if finish == "MAX_TOKENS":
        raise RuntimeError("Gemini output truncated (MAX_TOKENS)")
    if not text:
        raise RuntimeError(f"Gemini returned empty output ({finish or 'unknown'})")
    return text
