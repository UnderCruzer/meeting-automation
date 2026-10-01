from __future__ import annotations
"""
AI Orchestrator — analyse meeting transcript with the configured LLM (Gemini or Claude).

Extracts: topics, decisions, action items, participants, KR/EN summary, routing.
Uses structured output (Gemini responseSchema / Claude tool_use) for reliable JSON.
"""
import json
import logging
from pathlib import Path

import aiofiles

from app.models.analysis import OrchestratorOutput
from app.models.transcript import TranscriptResult
from app.services import llm
from app.services.diarization import format_diarized_transcript

logger = logging.getLogger(__name__)

_MAX_TOKENS = 4096
# Smallest supported context window is Claude's 200k tokens (~800k chars).
# Reserve headroom for system prompt, schema, and response.
_TRANSCRIPT_CHAR_LIMIT = 600_000

_ANALYSIS_TOOL = {
    "name": "analyse_meeting",
    "description": "Extract structured information from a meeting transcript.",
    "input_schema": {
        "type": "object",
        "properties": {
            "topics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "주요 논의 주제 목록 (최대 10개)",
            },
            "decisions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "회의에서 확정된 결정 사항 목록",
            },
            "action_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "assignee": {"type": "string"},
                        "due_date": {"type": "string"},
                        "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    },
                    "required": ["description"],
                },
                "description": "후속 조치 항목 목록",
            },
            "participants_mentioned": {
                "type": "array",
                "items": {"type": "string"},
                "description": "transcript에서 언급된 이름 또는 역할",
            },
            "summary_ko": {"type": "string", "description": "한국어 요약 (3-5문장)"},
            "summary_en": {"type": "string", "description": "English summary (3-5 sentences)"},
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "분석 신뢰도 (0: 낮음, 1: 높음)",
            },
            "routing": {
                "type": "array",
                "items": {"type": "string", "enum": ["jira", "confluence", "slack"]},
                "description": "생성이 필요한 artifact 종류",
            },
        },
        "required": [
            "topics", "decisions", "action_items", "participants_mentioned",
            "summary_ko", "summary_en", "confidence", "routing",
        ],
    },
}

_SYSTEM_PROMPT = """You are a professional meeting analyst. You will receive a meeting transcript and extract structured information from it.

Guidelines:
- topics: list the main discussion topics, not trivial side comments
- decisions: only list confirmed decisions, not suggestions or open questions
- action_items: extract specific tasks with assignees and deadlines when mentioned
- routing: include "jira" if action items require task tracking, "confluence" if documentation is needed, "slack" if a brief summary should be shared
- confidence: lower score (< 0.6) if transcript is short, fragmented, or unclear
- Tokens like [PERSON_1] are pseudonyms for real people and [MASKED_*] hides personal data: copy them exactly as written (e.g. assignee "[PERSON_1]"); never guess the real value
- Respond in the language of the transcript for summaries; always produce both KR and EN versions"""


async def analyse(
    transcript: TranscriptResult,
    masked_text: str | None = None,
) -> OrchestratorOutput:
    """
    Analyse a transcript with the configured LLM.
    Uses masked_text if available to avoid sending PII to the API.
    """
    text = masked_text if masked_text is not None else transcript.full_text
    if not text.strip():
        raise ValueError("Transcript is empty — cannot analyse")

    if len(text) > _TRANSCRIPT_CHAR_LIMIT:
        logger.warning(
            "[Orchestrator] Transcript too long (%d chars) — truncating to %d",
            len(text), _TRANSCRIPT_CHAR_LIMIT,
        )
        text = text[:_TRANSCRIPT_CHAR_LIMIT] + "\n\n[TRANSCRIPT TRUNCATED]"

    # Include speaker-labelled transcript when diarization has been applied
    has_diarization = len({s.speaker for s in transcript.segments}) > 1
    if has_diarization and masked_text is None:
        diarized_text = format_diarized_transcript(transcript)
        user_content = (
            f"Meeting transcript ({transcript.language}, {transcript.duration:.0f}s)"
            f" — speaker-labelled:\n\n{diarized_text}"
        )
    else:
        user_content = (
            f"Meeting transcript ({transcript.language}, {transcript.duration:.0f}s):\n\n{text}"
        )

    raw = await llm.generate_structured(
        prompt=user_content,
        system=_SYSTEM_PROMPT,
        name=_ANALYSIS_TOOL["name"],
        description=_ANALYSIS_TOOL["description"],
        schema=_ANALYSIS_TOOL["input_schema"],
        max_tokens=_MAX_TOKENS,
    )
    return OrchestratorOutput(meeting_id=transcript.meetingId, **raw)


async def save_analysis(analysis: OrchestratorOutput, file_key: str, base_dir: Path) -> Path:
    """Persist analysis JSON alongside the audio file."""
    analysis_path = base_dir / (file_key[:-4] + ".analysis.json")
    content = json.dumps(analysis.model_dump(), ensure_ascii=False, indent=2)
    async with aiofiles.open(analysis_path, "w", encoding="utf-8") as f:
        await f.write(content)
    return analysis_path
