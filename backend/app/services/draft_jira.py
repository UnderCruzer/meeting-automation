"""
Jira Draft Generator — decide create vs comment, generate issue/comment draft.

Uses Claude to decide whether to create a new Jira issue or add a comment to
an existing matched issue, then generates the full draft text.
"""
import json
import logging
import os
from pathlib import Path

import aiofiles
import anthropic

from app.models.analysis import OrchestratorOutput
from app.models.drafts import JiraDraftResult, JiraIssueDraft
from app.models.retrieval import RetrievalContext
from app.models.summary import MeetingSummary

logger = logging.getLogger(__name__)
_MODEL = "claude-sonnet-4-6"

_TOOL = {
    "name": "generate_jira_drafts",
    "description": "Generate Jira issue create or comment drafts from meeting analysis.",
    "input_schema": {
        "type": "object",
        "properties": {
            "drafts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["create", "comment"]},
                        "existing_key": {"type": "string"},
                        "summary": {"type": "string"},
                        "description": {"type": "string"},
                        "issue_type": {"type": "string", "enum": ["Task", "Bug", "Story", "Epic"]},
                        "priority": {"type": "string", "enum": ["Highest", "High", "Medium", "Low", "Lowest"]},
                        "assignee": {"type": "string"},
                        "labels": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["action", "summary", "description"],
                },
            }
        },
        "required": ["drafts"],
    },
}


async def generate_jira_drafts(
    summary: MeetingSummary,
    analysis: OrchestratorOutput,
    context: RetrievalContext,
) -> JiraDraftResult:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    jira_items = [i for i in context.items if i.source == "jira"]
    existing_summary = "\n".join(
        f"- [{i.id}] {i.title} ({i.url})" for i in jira_items
    ) or "없음"

    action_text = "\n".join(
        f"- {ai.description} (담당: {ai.assignee or '미정'}, 기한: {ai.due_date or '미정'}, 우선순위: {ai.priority})"
        for ai in summary.action_items
    ) or "없음"

    prompt = f"""다음 회의 분석 결과를 바탕으로 Jira 이슈 초안을 생성하세요.

## 회의 요약 (한국어)
{summary.summary_ko}

## Action Items
{action_text}

## 결정사항
{chr(10).join(f'- {d.text}' for d in summary.decisions) or '없음'}

## 기존 관련 Jira 이슈
{existing_summary}

지침:
- 기존 이슈와 명확히 연관된 action item은 해당 이슈에 comment로 생성하세요 (action=comment, existing_key 필수).
- 새로운 작업은 create로 생성하세요.
- description은 Jira wiki markup 형식으로 작성하세요.
- 한국어로 작성하세요."""

    client = anthropic.AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model=_MODEL,
        max_tokens=2048,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "generate_jira_drafts"},
        messages=[{"role": "user", "content": prompt}],
    )

    tool_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_block is None:
        raise RuntimeError("Claude did not return Jira drafts")

    drafts = [
        JiraIssueDraft(**d) for d in tool_block.input.get("drafts", [])
    ]
    return JiraDraftResult(meeting_id=summary.meeting_id, drafts=drafts)


async def save_jira_drafts(result: JiraDraftResult, file_key: str, base_dir: Path) -> Path:
    path = base_dir / (file_key[:-4] + ".jira_drafts.json")
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    return path
