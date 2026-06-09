"""
STT service — Whisper API (primary) with local Whisper fallback.

Primary:  OpenAI Whisper API (requires OPENAI_API_KEY, fast, no GPU needed)
Fallback: openai-whisper local model (requires `pip install openai-whisper` + ffmpeg)

Set STT_BACKEND=local in .env to force local model.
"""
import json
import logging
import os
from pathlib import Path

from app.models.transcript import TranscriptResult, TranscriptSegment

logger = logging.getLogger(__name__)

_STT_BACKEND = os.getenv("STT_BACKEND", "whisper-api")


async def transcribe(audio_path: Path, meeting_id: str) -> TranscriptResult:
    """Transcribe a WAV file and return a structured TranscriptResult."""
    if _STT_BACKEND == "local":
        return await _transcribe_local(audio_path, meeting_id)
    try:
        return await _transcribe_api(audio_path, meeting_id)
    except Exception as exc:
        logger.warning("Whisper API failed (%s), falling back to local model", exc)
        return await _transcribe_local(audio_path, meeting_id)


async def _transcribe_api(audio_path: Path, meeting_id: str) -> TranscriptResult:
    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    client = AsyncOpenAI(api_key=api_key)
    with open(audio_path, "rb") as f:
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    segments = [
        TranscriptSegment(
            start=seg.start,
            end=seg.end,
            text=seg.text.strip(),
        )
        for seg in (response.segments or [])
    ]
    full_text = " ".join(s.text for s in segments)

    return TranscriptResult(
        meetingId=meeting_id,
        language=response.language or "unknown",
        duration=response.duration or 0.0,
        segments=segments,
        full_text=full_text,
        backend="whisper-api",
    )


async def _transcribe_local(audio_path: Path, meeting_id: str) -> TranscriptResult:
    """Run openai-whisper in a thread so it doesn't block the event loop."""
    import asyncio
    import functools

    try:
        import whisper  # type: ignore
    except ImportError:
        raise RuntimeError(
            "openai-whisper not installed. Run: pip install openai-whisper"
        )

    model_name = os.getenv("WHISPER_LOCAL_MODEL", "base")

    def _run() -> dict:
        model = whisper.load_model(model_name)
        return model.transcribe(str(audio_path), task="transcribe")

    result = await asyncio.get_event_loop().run_in_executor(
        None, functools.partial(_run)
    )

    raw_segments = result.get("segments", [])
    segments = [
        TranscriptSegment(
            start=seg["start"],
            end=seg["end"],
            text=seg["text"].strip(),
        )
        for seg in raw_segments
    ]
    duration = raw_segments[-1]["end"] if raw_segments else 0.0
    full_text = result.get("text", "").strip()

    return TranscriptResult(
        meetingId=meeting_id,
        language=result.get("language", "unknown"),
        duration=duration,
        segments=segments,
        full_text=full_text,
        backend="whisper-local",
    )


async def save_transcript(transcript: TranscriptResult, audio_file_key: str, base_dir: Path) -> Path:
    """Save transcript JSON alongside the audio file."""
    transcript_path = base_dir / audio_file_key.replace(".wav", ".transcript.json")
    transcript_path.write_text(
        json.dumps(transcript.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return transcript_path
