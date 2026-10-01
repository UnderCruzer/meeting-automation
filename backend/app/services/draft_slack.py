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


_LABELS = {
    "ko": {"summary": "회의 요약", "decisions": "결정사항", "actions": "Action Items",
           "no_decisions": "결정사항 없음", "no_actions": "Action Item 없음", "unassigned": "미정"},
    "en": {"summary": "Meeting summary", "decisions": "Decisions", "actions": "Action items",
           "no_decisions": "No decisions", "no_actions": "No action items", "unassigned": "Unassigned"},
}


def generate_slack_draft(summary: MeetingSummary, lang: str = "ko") -> SlackBriefDraft:
    """Build a Slack mrkdwn brief from meeting summary (lang: "ko" | "en")."""
    channel = os.getenv("SLACK_BRIEF_CHANNEL", "general")
    labels = _LABELS["en" if lang == "en" else "ko"]

    # Collect assignees for mentions
    assignees = list({
        ai.assignee for ai in summary.action_items if ai.assignee
    })

    decisions_text = "\n".join(
        f"• {d.text}" for d in summary.decisions
    ) or f"• {labels['no_decisions']}"

    action_lines = "\n".join(
        f"• [{ai.priority.upper()}] {ai.description}"
        f" — *{ai.assignee or labels['unassigned']}*"
        f"{f' (~{ai.due_date})' if ai.due_date else ''}"
        for ai in summary.action_items
    ) or f"• {labels['no_actions']}"

    quality_note = ""
    blocking = [f for f in summary.quality_flags if f.code in {"LOW_CONFIDENCE", "SHORT_TRANSCRIPT"}]
    if blocking:
        quality_note = f"\n\n:warning: {blocking[0].message}"

    body = summary.summary_en if lang == "en" and summary.summary_en else summary.summary_ko
    text = (
        f":memo: *{labels['summary']}*\n"
        f"{body}\n\n"
        f":white_check_mark: *{labels['decisions']}*\n{decisions_text}\n\n"
        f":clipboard: *{labels['actions']}*\n{action_lines}"
        f"{quality_note}"
    )

    return SlackBriefDraft(
        text=text,
        suggested_channel=channel,
        mentions=assignees,
        language="en" if lang == "en" else "ko",
    )


async def save_slack_draft(draft: SlackBriefDraft, file_key: str, base_dir: Path) -> Path:
    path = base_dir / (file_key[:-4] + ".slack_draft.json")
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(draft.model_dump(), ensure_ascii=False, indent=2))
    return path
