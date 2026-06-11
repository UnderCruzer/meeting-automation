"""Unit tests for summarizer service — citation matching and quality validation."""
import pytest
from app.models.analysis import ActionItem, OrchestratorOutput
from app.models.transcript import TranscriptResult, TranscriptSegment
from app.services.summarizer import _find_best_segment, _is_blocking, _tokenize, _validate, build_summary


def _make_segment(text: str, start: float = 0.0, end: float = 5.0) -> TranscriptSegment:
    return TranscriptSegment(start=start, end=end, text=text)


def _make_analysis(**kwargs) -> OrchestratorOutput:
    defaults = dict(
        meeting_id="m1",
        topics=["배포 일정"],
        decisions=["다음 주 금요일 배포 확정"],
        action_items=[ActionItem(description="배포 스크립트 작성", assignee="김개발", priority="high")],
        participants_mentioned=["김개발"],
        summary_ko="회의 요약.",
        summary_en="Meeting summary.",
        confidence=0.8,
        routing=["jira"],
    )
    defaults.update(kwargs)
    return OrchestratorOutput(**defaults)


def _make_transcript(**kwargs) -> TranscriptResult:
    defaults = dict(
        meetingId="m1",
        language="ko",
        duration=120.0,
        segments=[
            _make_segment("다음 주 금요일에 배포를 확정했습니다.", 0, 5),
            _make_segment("배포 스크립트 작성은 김개발이 담당합니다.", 5, 10),
            _make_segment("컨플루언스 문서도 업데이트 필요합니다.", 10, 15),
        ],
        full_text="다음 주 금요일에 배포를 확정했습니다. 배포 스크립트 작성은 김개발이 담당합니다.",
        backend="whisper-api",
    )
    defaults.update(kwargs)
    return TranscriptResult(**defaults)


# ── _tokenize ─────────────────────────────────────────────────────────────────

class TestTokenize:
    def test_splits_on_spaces(self):
        assert "hello" in _tokenize("hello world")
        assert "world" in _tokenize("hello world")

    def test_drops_single_char_tokens(self):
        tokens = _tokenize("a is the big")
        assert "a" not in tokens   # len 1 — dropped
        assert "big" in tokens

    def test_lowercases(self):
        assert "배포" in _tokenize("배포 스크립트")

    def test_splits_on_punctuation(self):
        assert "hello" in _tokenize("hello, world.")
        assert "world" in _tokenize("hello, world.")


# ── _find_best_segment ────────────────────────────────────────────────────────

class TestFindBestSegment:
    def test_returns_matching_segment(self):
        segs = [
            _make_segment("배포 스크립트 작성", 0, 5),
            _make_segment("전혀 무관한 내용", 5, 10),
        ]
        result = _find_best_segment("배포 스크립트 작성 완료", segs)
        assert result is not None
        assert result.text == "배포 스크립트 작성"

    def test_returns_none_on_no_overlap(self):
        segs = [_make_segment("completely unrelated text here")]
        result = _find_best_segment("배포 스크립트", segs)
        assert result is None

    def test_returns_none_for_empty_segments(self):
        assert _find_best_segment("쿼리", []) is None

    def test_prefers_higher_overlap(self):
        segs = [
            _make_segment("배포 일정 논의", 0, 5),        # 1 match: 배포
            _make_segment("배포 스크립트 작성 완료", 5, 10),  # 3 matches
        ]
        result = _find_best_segment("배포 스크립트 작성", segs)
        assert result is not None
        assert result.start == 5.0


# ── _validate / _is_blocking ──────────────────────────────────────────────────

class TestValidate:
    def test_no_flags_for_healthy_meeting(self):
        analysis = _make_analysis()
        transcript = _make_transcript()
        flags = _validate(analysis, transcript)
        assert flags == []

    def test_low_confidence_flag(self):
        analysis = _make_analysis(confidence=0.3)
        flags = _validate(analysis, _make_transcript())
        codes = [f.code for f in flags]
        assert "LOW_CONFIDENCE" in codes

    def test_short_transcript_flag(self):
        transcript = _make_transcript(duration=10.0)
        flags = _validate(_make_analysis(), transcript)
        codes = [f.code for f in flags]
        assert "SHORT_TRANSCRIPT" in codes

    def test_few_segments_flag(self):
        transcript = _make_transcript(
            segments=[_make_segment("단 하나의 세그먼트")],
            duration=120.0,
        )
        flags = _validate(_make_analysis(), transcript)
        codes = [f.code for f in flags]
        assert "FEW_SEGMENTS" in codes

    def test_no_action_items_flag(self):
        analysis = _make_analysis(action_items=[])
        flags = _validate(analysis, _make_transcript())
        codes = [f.code for f in flags]
        assert "NO_ACTION_ITEMS" in codes

    def test_no_decisions_flag(self):
        analysis = _make_analysis(decisions=[])
        flags = _validate(analysis, _make_transcript())
        codes = [f.code for f in flags]
        assert "NO_DECISIONS" in codes


class TestIsBlocking:
    def test_low_confidence_is_blocking(self):
        from app.models.summary import QualityFlag
        assert _is_blocking(QualityFlag(code="LOW_CONFIDENCE", message=""))

    def test_short_transcript_is_blocking(self):
        from app.models.summary import QualityFlag
        assert _is_blocking(QualityFlag(code="SHORT_TRANSCRIPT", message=""))

    def test_no_action_items_not_blocking(self):
        from app.models.summary import QualityFlag
        assert not _is_blocking(QualityFlag(code="NO_ACTION_ITEMS", message=""))

    def test_no_decisions_not_blocking(self):
        from app.models.summary import QualityFlag
        assert not _is_blocking(QualityFlag(code="NO_DECISIONS", message=""))


# ── build_summary integration ─────────────────────────────────────────────────

class TestBuildSummary:
    def test_returns_meeting_summary(self):
        summary = build_summary(_make_analysis(), _make_transcript())
        assert summary.meeting_id == "m1"
        assert summary.summary_ko == "회의 요약."

    def test_quality_ok_when_no_blocking_flags(self):
        summary = build_summary(_make_analysis(), _make_transcript())
        assert summary.quality_ok is True

    def test_quality_not_ok_when_low_confidence(self):
        analysis = _make_analysis(confidence=0.2)
        summary = build_summary(analysis, _make_transcript())
        assert summary.quality_ok is False

    def test_citation_attached_when_keyword_overlap(self):
        summary = build_summary(_make_analysis(), _make_transcript())
        matched = [d for d in summary.decisions if d.citation_text]
        assert len(matched) >= 1

    def test_action_item_count_matches_input(self):
        summary = build_summary(_make_analysis(), _make_transcript())
        assert len(summary.action_items) == 1
        assert summary.action_items[0].description == "배포 스크립트 작성"
