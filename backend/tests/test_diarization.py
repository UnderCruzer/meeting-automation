"""Unit tests for diarization service."""
import pytest
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services.diarization import (
    _diarize_pause_fallback,
    _assign_speakers,
    format_diarized_transcript,
)


def _make_transcript(*segments: tuple[float, float, str], speaker: str = "SPEAKER_00") -> TranscriptResult:
    segs = [
        TranscriptSegment(start=s, end=e, text=t, speaker=speaker)
        for s, e, t in segments
    ]
    full_text = " ".join(s.text for s in segs)
    return TranscriptResult(
        meetingId="test-001",
        language="ko",
        duration=segs[-1].end if segs else 0.0,
        segments=segs,
        full_text=full_text,
        backend="whisper-api",
    )


class TestPauseFallback:
    def test_single_segment_gets_speaker_00(self):
        t = _make_transcript((0.0, 2.0, "Hello"))
        result = _diarize_pause_fallback(t)
        assert result.segments[0].speaker == "SPEAKER_00"

    def test_short_gap_keeps_same_speaker(self):
        # gap = 0.5s < threshold 1.5s
        t = _make_transcript((0.0, 2.0, "Hello"), (2.5, 4.0, "World"))
        result = _diarize_pause_fallback(t)
        assert result.segments[0].speaker == result.segments[1].speaker

    def test_long_gap_changes_speaker(self):
        # gap = 3.0s >= threshold 1.5s
        t = _make_transcript((0.0, 2.0, "Hello"), (5.0, 7.0, "World"))
        result = _diarize_pause_fallback(t)
        assert result.segments[0].speaker != result.segments[1].speaker

    def test_alternates_on_each_long_gap(self):
        t = _make_transcript(
            (0.0, 1.0, "A"),
            (4.0, 5.0, "B"),   # gap 3.0s → speaker changes
            (8.0, 9.0, "C"),   # gap 3.0s → speaker changes back
        )
        result = _diarize_pause_fallback(t)
        assert result.segments[0].speaker == result.segments[2].speaker
        assert result.segments[0].speaker != result.segments[1].speaker

    def test_empty_transcript_returns_unchanged(self):
        t = TranscriptResult(
            meetingId="empty",
            language="ko",
            duration=0.0,
            segments=[],
            full_text="",
            backend="whisper-api",
        )
        result = _diarize_pause_fallback(t)
        assert result.segments == []

    def test_speaker_labels_are_zero_padded(self):
        t = _make_transcript((0.0, 1.0, "A"), (5.0, 6.0, "B"))
        result = _diarize_pause_fallback(t)
        for seg in result.segments:
            assert seg.speaker.startswith("SPEAKER_")
            assert len(seg.speaker.split("_")[1]) == 2

    def test_original_transcript_not_mutated(self):
        t = _make_transcript((0.0, 2.0, "Hello"), (5.0, 7.0, "World"))
        original_speakers = [s.speaker for s in t.segments]
        _diarize_pause_fallback(t)
        assert [s.speaker for s in t.segments] == original_speakers

    def test_meeting_id_preserved(self):
        t = _make_transcript((0.0, 2.0, "Hello"))
        result = _diarize_pause_fallback(t)
        assert result.meetingId == "test-001"

    def test_multiple_long_gaps(self):
        t = _make_transcript(
            (0.0, 1.0, "A"),
            (5.0, 6.0, "B"),
            (10.0, 11.0, "C"),
            (15.0, 16.0, "D"),
        )
        result = _diarize_pause_fallback(t)
        speakers = [s.speaker for s in result.segments]
        # Should alternate: 00, 01, 00, 01
        assert speakers[0] == speakers[2]
        assert speakers[1] == speakers[3]
        assert speakers[0] != speakers[1]


class TestAssignSpeakers:
    def test_exact_overlap_assigns_correct_speaker(self):
        segments = [TranscriptSegment(start=0.0, end=2.0, text="Hello")]
        turns = [(0.0, 2.0, "SPEAKER_00")]
        result = _assign_speakers(segments, turns)
        assert result[0].speaker == "SPEAKER_00"

    def test_best_overlap_wins(self):
        segments = [TranscriptSegment(start=0.0, end=4.0, text="Long segment")]
        turns = [
            (0.0, 1.0, "SPEAKER_00"),  # overlap 1.0
            (1.0, 4.0, "SPEAKER_01"),  # overlap 3.0 — wins
        ]
        result = _assign_speakers(segments, turns)
        assert result[0].speaker == "SPEAKER_01"

    def test_no_overlap_defaults_to_speaker_00(self):
        segments = [TranscriptSegment(start=10.0, end=12.0, text="Late segment")]
        turns = [(0.0, 2.0, "SPEAKER_00")]
        result = _assign_speakers(segments, turns)
        assert result[0].speaker == "SPEAKER_00"

    def test_empty_segments_returns_empty(self):
        result = _assign_speakers([], [(0.0, 2.0, "SPEAKER_00")])
        assert result == []

    def test_multiple_segments(self):
        segments = [
            TranscriptSegment(start=0.0, end=2.0, text="A"),
            TranscriptSegment(start=3.0, end=5.0, text="B"),
        ]
        turns = [
            (0.0, 2.0, "SPEAKER_00"),
            (3.0, 5.0, "SPEAKER_01"),
        ]
        result = _assign_speakers(segments, turns)
        assert result[0].speaker == "SPEAKER_00"
        assert result[1].speaker == "SPEAKER_01"


class TestFormatDiarizedTranscript:
    def test_single_speaker_no_label_repetition(self):
        t = _make_transcript((0.0, 1.0, "Hello"), (1.5, 2.5, "World"), speaker="SPEAKER_00")
        result = format_diarized_transcript(t)
        assert result.count("SPEAKER_00:") == 1
        assert "Hello World" in result

    def test_two_speakers_formatted_correctly(self):
        segs = [
            TranscriptSegment(start=0.0, end=1.0, text="Hi", speaker="SPEAKER_00"),
            TranscriptSegment(start=2.0, end=3.0, text="Hello", speaker="SPEAKER_01"),
        ]
        t = TranscriptResult(
            meetingId="t1", language="en", duration=3.0,
            segments=segs, full_text="Hi Hello", backend="whisper-api",
        )
        result = format_diarized_transcript(t)
        assert "SPEAKER_00: Hi" in result
        assert "SPEAKER_01: Hello" in result

    def test_empty_transcript_returns_empty_string(self):
        t = TranscriptResult(
            meetingId="t1", language="en", duration=0.0,
            segments=[], full_text="", backend="whisper-api",
        )
        assert format_diarized_transcript(t) == ""

    def test_consecutive_same_speaker_merged(self):
        segs = [
            TranscriptSegment(start=0.0, end=1.0, text="First", speaker="SPEAKER_00"),
            TranscriptSegment(start=1.2, end=2.0, text="Second", speaker="SPEAKER_00"),
            TranscriptSegment(start=3.0, end=4.0, text="Third", speaker="SPEAKER_01"),
        ]
        t = TranscriptResult(
            meetingId="t1", language="en", duration=4.0,
            segments=segs, full_text="", backend="whisper-api",
        )
        result = format_diarized_transcript(t)
        lines = result.strip().split("\n")
        assert len(lines) == 2
        assert "First Second" in lines[0]
