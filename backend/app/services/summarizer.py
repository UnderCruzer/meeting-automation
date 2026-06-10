"""
Meeting summarizer — enriches OrchestratorOutput with transcript citations
and runs quality validation checks.

Citation matching: simple keyword overlap between decision/action text
and transcript segment text (no embeddings needed for MVP).
"""
import json
import logging
from pathlib import Path

import re

import aiofiles

from app.models.analysis import OrchestratorOutput
from app.models.summary import CitedActionItem, CitedDecision, MeetingSummary, QualityFlag
from app.models.transcript import TranscriptResult

logger = logging.getLogger(__name__)

# Quality thresholds
_MIN_CONFIDENCE = 0.5
_MIN_DURATION_SECONDS = 30
_MIN_SEGMENTS = 3


def build_summary(
    analysis: OrchestratorOutput,
    transcript: TranscriptResult,
) -> MeetingSummary:
    """Enrich analysis with citations and validate quality."""
    segments = transcript.segments

    cited_decisions = [
        _cite_decision(d, segments) for d in analysis.decisions
    ]
    cited_action_items = [
        _cite_action_item(ai, segments) for ai in analysis.action_items
    ]
    flags = _validate(analysis, transcript)
    quality_ok = not any(_is_blocking(f) for f in flags)

    return MeetingSummary(
        meeting_id=analysis.meeting_id,
        summary_ko=analysis.summary_ko,
        summary_en=analysis.summary_en,
        decisions=cited_decisions,
        action_items=cited_action_items,
        quality_flags=flags,
        quality_ok=quality_ok,
    )


def _cite_decision(text: str, segments) -> CitedDecision:
    seg = _find_best_segment(text, segments)
    if seg:
        return CitedDecision(
            text=text,
            citation_start=seg.start,
            citation_end=seg.end,
            citation_text=seg.text,
        )
    return CitedDecision(text=text)


def _cite_action_item(ai, segments) -> CitedActionItem:
    seg = _find_best_segment(ai.description, segments)
    if seg:
        return CitedActionItem(
            description=ai.description,
            assignee=ai.assignee,
            due_date=ai.due_date,
            priority=ai.priority,
            citation_start=seg.start,
            citation_end=seg.end,
            citation_text=seg.text,
        )
    return CitedActionItem(
        description=ai.description,
        assignee=ai.assignee,
        due_date=ai.due_date,
        priority=ai.priority,
    )


def _find_best_segment(query: str, segments):
    """Return the transcript segment with highest keyword overlap with query."""
    if not segments:
        return None
    query_words = set(_tokenize(query))
    if not query_words:
        return None

    best_seg = None
    best_score = 0.0
    for seg in segments:
        seg_words = set(_tokenize(seg.text))
        if not seg_words:
            continue
        overlap = len(query_words & seg_words) / len(query_words)
        if overlap > best_score:
            best_score = overlap
            best_seg = seg

    # Only cite if there's meaningful overlap (at least 1 keyword match)
    return best_seg if best_score > 0 else None


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on whitespace and punctuation, drop short tokens."""
    tokens = re.split(r"[\s\.,!?;:\"\'()\[\]]+", text.lower())
    return [t for t in tokens if len(t) >= 2]


def _validate(analysis: OrchestratorOutput, transcript: TranscriptResult) -> list[QualityFlag]:
    flags: list[QualityFlag] = []

    if analysis.confidence < _MIN_CONFIDENCE:
        flags.append(QualityFlag(
            code="LOW_CONFIDENCE",
            message=f"분석 신뢰도 {analysis.confidence:.0%} — 회의 내용이 불명확하거나 짧을 수 있습니다.",
        ))

    if transcript.duration < _MIN_DURATION_SECONDS:
        flags.append(QualityFlag(
            code="SHORT_TRANSCRIPT",
            message=f"녹음 시간 {transcript.duration:.0f}초 — 너무 짧아 요약 품질이 낮을 수 있습니다.",
        ))

    if len(transcript.segments) < _MIN_SEGMENTS:
        flags.append(QualityFlag(
            code="FEW_SEGMENTS",
            message="Transcript 세그먼트가 3개 미만입니다. STT 결과를 확인해주세요.",
        ))

    if not analysis.action_items:
        flags.append(QualityFlag(
            code="NO_ACTION_ITEMS",
            message="Action Item이 감지되지 않았습니다. 회의에서 후속 조치가 논의되었는지 확인하세요.",
        ))

    if not analysis.decisions:
        flags.append(QualityFlag(
            code="NO_DECISIONS",
            message="결정사항이 감지되지 않았습니다.",
        ))

    return flags


def _is_blocking(flag: QualityFlag) -> bool:
    """Only LOW_CONFIDENCE and SHORT_TRANSCRIPT block downstream processing."""
    return flag.code in {"LOW_CONFIDENCE", "SHORT_TRANSCRIPT"}


async def save_summary(summary: MeetingSummary, file_key: str, base_dir: Path) -> Path:
    summary_path = base_dir / (file_key[:-4] + ".summary.json")
    content = json.dumps(summary.model_dump(), ensure_ascii=False, indent=2)
    async with aiofiles.open(summary_path, "w", encoding="utf-8") as f:
        await f.write(content)
    return summary_path
