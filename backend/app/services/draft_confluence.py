"""
Confluence Draft Generator — meeting minutes page in Confluence storage format.
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import aiofiles

from app.models.drafts import ConfluenceDraft
from app.models.summary import MeetingSummary

logger = logging.getLogger(__name__)


def generate_confluence_draft(summary: MeetingSummary) -> ConfluenceDraft:
    """Build a Confluence page draft (storage format HTML) from meeting summary."""
    space_key = os.getenv("CONFLUENCE_SPACE_KEY", "TEAM")
    parent_page_id = os.getenv("CONFLUENCE_MEETING_PARENT_PAGE_ID", "")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    title = f"회의록 — {now} ({summary.meeting_id[:8]})"

    decisions_html = "".join(
        f"<li>{_escape(d.text)}"
        f"{f' <em>[{d.citation_start:.0f}s]</em>' if d.citation_text else ''}</li>"
        for d in summary.decisions
    ) or "<li>결정사항 없음</li>"

    action_rows = "".join(
        f"<tr>"
        f"<td>{_escape(ai.description)}</td>"
        f"<td>{_escape(ai.assignee) or '미정'}</td>"
        f"<td>{_escape(ai.due_date) or '미정'}</td>"
        f"<td>{_escape(ai.priority)}</td>"
        f"</tr>"
        for ai in summary.action_items
    )

    quality_block = ""
    if summary.quality_flags:
        flags_html = "".join(
            f"<li><strong>{f.code}</strong>: {_escape(f.message)}</li>"
            for f in summary.quality_flags
        )
        quality_block = f"<h2>⚠️ 품질 알림</h2><ul>{flags_html}</ul>"

    body = f"""<h1>회의록</h1>
<p><strong>요약 (한국어)</strong></p>
<blockquote>{_escape(summary.summary_ko)}</blockquote>
<p><strong>Summary (English)</strong></p>
<blockquote>{_escape(summary.summary_en)}</blockquote>

<h2>결정사항</h2>
<ul>{decisions_html}</ul>

<h2>Action Items</h2>
<table>
  <thead><tr><th>내용</th><th>담당자</th><th>기한</th><th>우선순위</th></tr></thead>
  <tbody>{action_rows or '<tr><td colspan="4">Action Item 없음</td></tr>'}</tbody>
</table>

{quality_block}
"""

    return ConfluenceDraft(
        title=title,
        body=body,
        space_key=space_key,
        parent_page_id=parent_page_id,
    )


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def save_confluence_draft(draft: ConfluenceDraft, file_key: str, base_dir: Path) -> Path:
    path = base_dir / (file_key[:-4] + ".confluence_draft.json")
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(draft.model_dump(), ensure_ascii=False, indent=2))
    return path
