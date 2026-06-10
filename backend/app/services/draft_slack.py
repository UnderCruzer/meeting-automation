"""
Slack Brief Draft Generator — compact mrkdwn summary for Slack channels.
"""
import json
import logging
import os
from pathlib import Path

import aiofiles

from app.models.drafts import SlackBriefDraft
from app.models.summary import MeetingSummary

logger = logging.getLogger(__name__)


def generate_slack_draft(summary: MeetingSummary) -> SlackBriefDraft:
    """Build a Slack mrkdwn brief from meeting summary."""
    channel = os.getenv("SLACK_BRIEF_CHANNEL", "general")

    # Collect assignees for mentions
    assignees = list({
        ai.assignee for ai in summary.action_items if ai.assignee
    })

    decisions_text = "\n".join(
        f"• {d.text}" for d in summary.decisions
    ) or "• 결정사항 없음"

    action_lines = "\n".join(
        f"• [{ai.priority.upper()}] {ai.description}"
        f" — *{ai.assignee or '미정'}*"
        f"{f' (~{ai.due_date})' if ai.due_date else ''}"
        for ai in summary.action_items
    ) or "• Action Item 없음"

    quality_note = ""
    blocking = [f for f in summary.quality_flags if f.code in {"LOW_CONFIDENCE", "SHORT_TRANSCRIPT"}]
    if blocking:
        quality_note = f"\n\n:warning: {blocking[0].message}"

    text = (
        f":memo: *회의 요약*\n"
        f"{summary.summary_ko}\n\n"
        f":white_check_mark: *결정사항*\n{decisions_text}\n\n"
        f":clipboard: *Action Items*\n{action_lines}"
        f"{quality_note}"
    )

    return SlackBriefDraft(
        text=text,
        suggested_channel=channel,
        mentions=assignees,
    )


async def save_slack_draft(draft: SlackBriefDraft, file_key: str, base_dir: Path) -> Path:
    path = base_dir / (file_key[:-4] + ".slack_draft.json")
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(draft.model_dump(), ensure_ascii=False, indent=2))
    return path
