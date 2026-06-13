"""
Speaker Diarization service — assigns speaker labels to transcript segments.

Primary:  pyannote.audio (requires HF_TOKEN env var and GPU-optional)
Fallback: pause-based heuristic (no external deps, lower accuracy)

The output enriches each TranscriptSegment.speaker field with a label
such as "SPEAKER_00", "SPEAKER_01", etc.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import os
from pathlib import Path

from app.models.transcript import TranscriptResult, TranscriptSegment

logger = logging.getLogger(__name__)

# Minimum silence gap (seconds) used by the pause-based fallback
# to detect a likely speaker change.
_PAUSE_THRESHOLD = 1.5


async def diarize(audio_path: Path, transcript: TranscriptResult) -> TranscriptResult:
    """Assign speaker labels to transcript segments.

    Tries pyannote.audio first; falls back to pause-based heuristic when
    HF_TOKEN is absent or pyannote is not installed.

    Returns a new TranscriptResult with speaker fields populated.
    """
    hf_token = os.getenv("HF_TOKEN", "")
    if hf_token:
        try:
            return await _diarize_pyannote(audio_path, transcript, hf_token)
        except Exception as exc:
            logger.warning("[Diarization] pyannote failed (%s) — using pause fallback", exc)

    return _diarize_pause_fallback(transcript)


async def _diarize_pyannote(
    audio_path: Path,
    transcript: TranscriptResult,
    hf_token: str,
) -> TranscriptResult:
    """Use pyannote.audio pipeline to produce speaker-turn segments."""
    try:
        from pyannote.audio import Pipeline  # type: ignore
    except ImportError:
        raise RuntimeError(
            "pyannote.audio not installed. Run: pip install pyannote.audio"
        )

    def _run() -> list[tuple[float, float, str]]:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )
        diarization = pipeline(str(audio_path))
        turns: list[tuple[float, float, str]] = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            turns.append((turn.start, turn.end, speaker))
        return turns

    turns = await asyncio.get_event_loop().run_in_executor(
        None, functools.partial(_run)
    )

    enriched = _assign_speakers(transcript.segments, turns)
    return transcript.model_copy(update={"segments": enriched})


def _diarize_pause_fallback(transcript: TranscriptResult) -> TranscriptResult:
    """Assign speaker labels based on silence gaps between segments.

    When a gap >= _PAUSE_THRESHOLD seconds is detected the speaker label
    alternates. This is a rough heuristic for two-speaker conversations.
    """
    if not transcript.segments:
        return transcript

    enriched: list[TranscriptSegment] = []
    speaker_index = 0
    prev_end = transcript.segments[0].start

    for seg in transcript.segments:
        gap = seg.start - prev_end
        if gap >= _PAUSE_THRESHOLD:
            speaker_index = (speaker_index + 1) % 2
        label = f"SPEAKER_{speaker_index:02d}"
        enriched.append(seg.model_copy(update={"speaker": label}))
        prev_end = seg.end

    logger.info(
        "[Diarization] Pause fallback assigned %d speaker(s) across %d segments",
        len({s.speaker for s in enriched}),
        len(enriched),
    )
    return transcript.model_copy(update={"segments": enriched})


def _assign_speakers(
    segments: list[TranscriptSegment],
    turns: list[tuple[float, float, str]],
) -> list[TranscriptSegment]:
    """Map pyannote diarization turns onto transcript segments by overlap."""
    enriched: list[TranscriptSegment] = []
    for seg in segments:
        best_speaker = "SPEAKER_00"
        best_overlap = 0.0
        for turn_start, turn_end, speaker in turns:
            overlap = min(seg.end, turn_end) - max(seg.start, turn_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker
        enriched.append(seg.model_copy(update={"speaker": best_speaker}))
    return enriched


def format_diarized_transcript(transcript: TranscriptResult) -> str:
    """Render a speaker-labelled transcript string for the AI prompt.

    Example output:
        SPEAKER_00: We need to finalize the budget by Friday.
        SPEAKER_01: Agreed. I will prepare the report.
    """
    lines: list[str] = []
    current_speaker: str | None = None
    current_lines: list[str] = []

    for seg in transcript.segments:
        if seg.speaker != current_speaker:
            if current_speaker is not None and current_lines:
                lines.append(f"{current_speaker}: {' '.join(current_lines)}")
            current_speaker = seg.speaker
            current_lines = [seg.text]
        else:
            current_lines.append(seg.text)

    if current_speaker and current_lines:
        lines.append(f"{current_speaker}: {' '.join(current_lines)}")

    return "\n".join(lines)
