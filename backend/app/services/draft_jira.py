"""
Jira Draft Generator — decide create vs comment, generate issue/comment draft.

Uses the configured LLM to decide whether to create a new Jira issue or add a comment to
an existing matched issue, then generates the full draft text.
"""
import json
import logging
from pathlib import Path

import aiofiles

from app.models.analysis import OrchestratorOutput
from app.models.drafts import JiraDraftResult, JiraIssueDraft
from app.models.retrieval import RetrievalContext
from app.models.summary import MeetingSummary
from app.services import llm

logger = logging.getLogger(__name__)

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
                        "priority": {"type": "string", "enum": ["High", "Medium", "Low"]},
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
    protect=lambda text: text,
) -> JiraDraftResult:
    """`protect` masks text that did not come through the transcript guard (related issue titles)."""
    jira_items = [i for i in context.items if i.source == "jira"]
    existing_summary = "\n".join(
        f"- [{i.id}] {protect(i.title)}" for i in jira_items
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
- Action Item마다 초안 하나, 최대 10개.
- 위 "기존 관련 Jira 이슈"와 명확히 같은 작업이면 그 이슈에 comment로 작성하세요 (action=comment, existing_key는 목록의 키만).
- 그 밖의 작업은 create로 작성하세요. summary는 80자 이내의 할 일 제목입니다.
- description은 일반 텍스트로, 배경·담당·기한을 줄바꿈과 "- " 목록으로 정리하세요.
- [PERSON_n] 같은 표기는 그대로 두세요.
- 한국어로 작성하세요."""

    raw = await llm.generate_structured(
        prompt=prompt,
        name=_TOOL["name"],
        description=_TOOL["description"],
        schema=_TOOL["input_schema"],
        max_tokens=2048,
    )

    drafts = [
        JiraIssueDraft(**d) for d in raw.get("drafts", [])
    ]
    return JiraDraftResult(meeting_id=summary.meeting_id, drafts=drafts)


async def save_jira_drafts(result: JiraDraftResult, file_key: str, base_dir: Path) -> Path:
    path = base_dir / (file_key[:-4] + ".jira_drafts.json")
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    return path
