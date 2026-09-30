"""
STT service — Whisper API (primary) with local Whisper fallback.

Primary:  OpenAI Whisper API (requires OPENAI_API_KEY, fast, no GPU needed)
Fallback: openai-whisper local model (requires `pip install openai-whisper` + ffmpeg)

Set STT_BACKEND=local in .env to force local model.
"""
import asyncio
import functools
import io
import json
import logging
import os
import wave
from pathlib import Path

import aiofiles

from app.models.transcript import TranscriptResult, TranscriptSegment

logger = logging.getLogger(__name__)


async def transcribe(audio_path: Path, meeting_id: str) -> TranscriptResult:
    """Transcribe a WAV file, apply speaker diarization, and return TranscriptResult."""
    from app.services.diarization import diarize

    backend = os.getenv("STT_BACKEND", "whisper-api")
    if backend == "local":
        result = await _transcribe_local(audio_path, meeting_id)
    else:
        try:
            result = await _transcribe_api(audio_path, meeting_id)
        except Exception as exc:
            logger.warning("Whisper API failed (%s), falling back to local model", exc)
            result = await _transcribe_local(audio_path, meeting_id)

    return await diarize(audio_path, result)


# Groq/OpenAI Whisper API reject files over 25 MB (~13 min of 16kHz mono WAV).
_API_MAX_BYTES = 24 * 1024 * 1024
_DEFAULT_CHUNK_SECONDS = 600


def _split_wav(audio_bytes: bytes, max_bytes: int = 0) -> list[tuple[float, bytes]]:
    """Split WAV bytes into (offset_seconds, wav_bytes) chunks that fit the API limit.

    Non-WAV input or input already under the limit is returned as a single chunk.
    """
    max_bytes = max_bytes or _API_MAX_BYTES
    if len(audio_bytes) <= max_bytes:
        return [(0.0, audio_bytes)]
    try:
        src = wave.open(io.BytesIO(audio_bytes), "rb")
    except (wave.Error, EOFError):
        return [(0.0, audio_bytes)]

    with src:
        params = src.getparams()
        rate = params.framerate
        frame_bytes = params.sampwidth * params.nchannels
        chunk_seconds = float(os.getenv("STT_CHUNK_SECONDS", _DEFAULT_CHUNK_SECONDS))
        # Never exceed the byte limit, whatever STT_CHUNK_SECONDS says (44 = WAV header).
        max_frames = (max_bytes - 44) // frame_bytes
        frames_per_chunk = max(1, min(int(chunk_seconds * rate), max_frames))

        chunks: list[tuple[float, bytes]] = []
        position = 0
        while True:
            frames = src.readframes(frames_per_chunk)
            if not frames:
                break
            buf = io.BytesIO()
            with wave.open(buf, "wb") as dst:
                dst.setparams(params)
                dst.writeframes(frames)
            chunks.append((position / rate, buf.getvalue()))
            position += len(frames) // frame_bytes
    return chunks


def _seg_value(seg, key):
    return seg[key] if isinstance(seg, dict) else getattr(seg, key)


async def _transcribe_chunk(audio_bytes: bytes) -> tuple[list[TranscriptSegment], str, float, str]:
    """Transcribe one API-sized chunk. Returns (segments, language, duration, backend)."""
    groq_key = os.getenv("GROQ_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if groq_key:
        from groq import AsyncGroq
        client = AsyncGroq(api_key=groq_key)
        response = await client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=("recording.wav", io.BytesIO(audio_bytes), "audio/wav"),
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
        backend = "groq-whisper"
    elif openai_key:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise RuntimeError("openai package not installed. Run: pip install openai")
        client = AsyncOpenAI(api_key=openai_key)
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=("recording.wav", io.BytesIO(audio_bytes), "audio/wav"),
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
        backend = "whisper-api"
    else:
        raise RuntimeError("OPENAI_API_KEY or GROQ_API_KEY not set")

    segments = [
        TranscriptSegment(
            start=_seg_value(seg, "start"),
            end=_seg_value(seg, "end"),
            text=_seg_value(seg, "text").strip(),
        )
        for seg in (response.segments or [])
    ]
    lang = response.language if isinstance(response.language, str) else ""
    dur = response.duration if isinstance(response.duration, (int, float)) else 0.0
    return segments, lang or "unknown", float(dur), backend


async def _transcribe_api(audio_path: Path, meeting_id: str) -> TranscriptResult:
    audio_bytes = await asyncio.get_event_loop().run_in_executor(
        None, audio_path.read_bytes
    )
    chunks = _split_wav(audio_bytes)
    if len(chunks) > 1:
        logger.info("[STT] %s — splitting into %d chunks for API limit", meeting_id, len(chunks))

    segments: list[TranscriptSegment] = []
    language = "unknown"
    duration = 0.0
    backend = "whisper-api"
    # Sequential on purpose: keeps provider rate limits predictable.
    for offset, chunk in chunks:
        chunk_segments, chunk_lang, chunk_dur, backend = await _transcribe_chunk(chunk)
        segments.extend(
            TranscriptSegment(start=s.start + offset, end=s.end + offset, text=s.text)
            for s in chunk_segments
        )
        if language == "unknown":
            language = chunk_lang
        duration = offset + chunk_dur

    return TranscriptResult(
        meetingId=meeting_id,
        language=language,
        duration=duration,
        segments=segments,
        full_text=" ".join(s.text for s in segments),
        backend=backend,
    )


async def _transcribe_local(audio_path: Path, meeting_id: str) -> TranscriptResult:
    """Run openai-whisper in a thread so it doesn't block the event loop."""
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
    """Save transcript JSON alongside the audio file (async to avoid blocking event loop)."""
    transcript_path = base_dir / (audio_file_key[:-4] + ".transcript.json")
    content = json.dumps(transcript.model_dump(), ensure_ascii=False, indent=2)
    async with aiofiles.open(transcript_path, "w", encoding="utf-8") as f:
        await f.write(content)
    return transcript_path
