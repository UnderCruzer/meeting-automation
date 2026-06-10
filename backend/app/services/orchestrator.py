from __future__ import annotations
"""
AI Orchestrator — analyse meeting transcript with Claude API.

Extracts: topics, decisions, action items, participants, KR/EN summary, routing.
Uses claude-sonnet-4-6 with tool_use to get structured JSON output reliably.
"""
import json
import logging
import os
from pathlib import Path

import aiofiles
import anthropic

from app.models.analysis import OrchestratorOutput
from app.models.transcript import TranscriptResult

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4096

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
- Respond in the language of the transcript for summaries; always produce both KR and EN versions"""


async def analyse(
    transcript: TranscriptResult,
    masked_text: str | None = None,
) -> OrchestratorOutput:
    """
    Analyse a transcript with Claude API.
    Uses masked_text if available to avoid sending PII to the API.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    text = masked_text if masked_text is not None else transcript.full_text
    if not text.strip():
        raise ValueError("Transcript is empty — cannot analyse")

    user_content = (
        f"Meeting transcript ({transcript.language}, {transcript.duration:.0f}s):\n\n{text}"
    )

    client = anthropic.AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        tools=[_ANALYSIS_TOOL],
        tool_choice={"type": "tool", "name": "analyse_meeting"},
        messages=[{"role": "user", "content": user_content}],
    )

    # Extract tool_use block
    tool_block = next(
        (b for b in response.content if b.type == "tool_use"),
        None,
    )
    if tool_block is None:
        raise RuntimeError("Claude did not return a tool_use block")

    raw: dict = tool_block.input  # already a dict when using tool_use
    return OrchestratorOutput(meeting_id=transcript.meetingId, **raw)


async def save_analysis(analysis: OrchestratorOutput, file_key: str, base_dir: Path) -> Path:
    """Persist analysis JSON alongside the audio file."""
    analysis_path = base_dir / (file_key[:-4] + ".analysis.json")
    content = json.dumps(analysis.model_dump(), ensure_ascii=False, indent=2)
    async with aiofiles.open(analysis_path, "w", encoding="utf-8") as f:
        await f.write(content)
    return analysis_path
