"""Jira / Confluence drafts for the review screen, and publishing them after approval.

Workflow 10 (search the configured project/space) → 12·13 (drafts) → 15·16 (review, approve per
artifact) → 17 (Write Queue creates them). Drafts are stored with the meeting (`jobs.drafts`):

    {"related": [...search results...],
     "jira": {"drafts": [{action, existing_key, summary, description, priority, include, result?}],
              "status": queued|sent|failed|None, "error": str|None, "generation_error": str|None},
     "confluence": {"title", "include", "status", "result", "error"}}
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date

from app.models.analysis import OrchestratorOutput
from app.models.retrieval import RetrievalContext
from app.models.summary import MeetingSummary
from app.services import atlassian
from app.services.draft_confluence import generate_confluence_draft
from app.services.draft_jira import generate_jira_drafts
from app.services.guard import detect_and_mask
from app.services.llm import LLMUnavailable
from app.services.name_guard import unmask_model
from app.services.retrieval import retrieve_context
from app.services.write_queue import WriteTask, enqueue

logger = logging.getLogger(__name__)

MAX_JIRA_DRAFTS = 10
_PRIORITIES = {"high": "High", "medium": "Medium", "low": "Low"}


def enabled() -> dict[str, bool]:
    return {"jira": atlassian.jira_site() is not None, "confluence": atlassian.confluence_site() is not None}


def _protector(name_tokens: dict[str, str]):
    """Mask PII patterns and the meeting's known names in text from Jira before it reaches the LLM."""
    names = sorted(((name, token) for token, name in name_tokens.items()), key=lambda p: -len(p[0]))

    def protect(text: str) -> str:
        text = detect_and_mask(text).masked_text
        for name, token in names:
            text = text.replace(name, token)
        return text

    return protect


async def prepare(analysis: OrchestratorOutput, masked_summary: MeetingSummary, name_tokens: dict[str, str],
                  title: str, meeting_day: date) -> dict | None:
    """Search + drafts for the configured products; None when Atlassian isn't set up.

    Never raises: a search or draft failure leaves the meeting reviewable without that draft.
    """
    sources = [name for name, on in enabled().items() if on]
    if not sources:
        return None
    try:
        context = await retrieve_context(analysis, sources=sources)
    except Exception:
        logger.exception("[Atlassian] search failed for %s", analysis.meeting_id)
        context = RetrievalContext(meeting_id=analysis.meeting_id, items=[], sources_searched=[])

    drafts: dict = {"related": [item.model_dump() for item in context.items]}
    if "jira" in sources:
        drafts["jira"] = await _jira_drafts(analysis, masked_summary, name_tokens, context)
    if "confluence" in sources:
        drafts["confluence"] = {"title": f"회의록 {meeting_day.isoformat()} — {title}"[:200], "include": True,
                                "status": None, "result": None, "error": None}
    return drafts


async def _jira_drafts(analysis, masked_summary, name_tokens, context) -> dict:
    section = {"drafts": [], "status": None, "error": None, "generation_error": None}
    if not masked_summary.action_items:
        return section
    try:
        result = await generate_jira_drafts(masked_summary, analysis, context, protect=_protector(name_tokens))
        result = unmask_model(result, name_tokens)
    except LLMUnavailable:
        section["generation_error"] = "LLM_BUSY"
        return section
    except Exception:
        logger.exception("[Atlassian] Jira draft generation failed for %s", analysis.meeting_id)
        section["generation_error"] = "DRAFT_FAILED"
        return section

    site = atlassian.jira_site()
    related = {item.id for item in context.items if item.source == "jira"}
    for draft in result.drafts[:MAX_JIRA_DRAFTS]:
        # A comment is only allowed on an issue the search actually found in the project.
        comment = draft.action == "comment" and draft.existing_key in related and site is not None \
            and atlassian.valid_issue_key(draft.existing_key, site.scope)
        section["drafts"].append({
            "action": "comment" if comment else "create",
            "existing_key": draft.existing_key if comment else "",
            "summary": (draft.summary or "")[:250] or "회의 후속 작업",
            "description": (draft.description or "")[:5000],
            "priority": draft.priority if draft.priority in _PRIORITIES.values() else "Medium",
            "include": True,
        })
    return section


def confluence_body(summary: dict) -> str:
    return generate_confluence_draft(MeetingSummary.model_validate(summary)).body


def has_pending(drafts: dict | None, artifact: str) -> bool:
    """Something approved for `artifact` that has not been created yet."""
    section = (drafts or {}).get(artifact)
    if not section:
        return False
    if artifact == "jira":
        return any(d.get("include") and not d.get("result") for d in section.get("drafts", []))
    return bool(section.get("include")) and not section.get("result")


_FAIL_DETAIL = re.compile(r"\s+")


async def publish(workspace, audit, storage, job: dict, artifact: str, requested_by: str | None) -> dict:
    """Queue creation of the approved Jira issues or Confluence page. Returns the new section state."""
    job_id, drafts = job["id"], job.get("drafts") or {}
    if artifact == "jira":
        payload = {"drafts": [{**d, "index": i} for i, d in enumerate(drafts["jira"]["drafts"]) if d.get("include")]}
    else:
        section = drafts["confluence"]
        payload = {"title": section["title"], "body": confluence_body(job["summary"]), "suffix": job_id[:6],
                   "result": section.get("result")}
    folder = next((path.parent.name for path in storage.base_dir.glob(f"*/{job_id}.*")), "workspace")

    async def still_wanted() -> bool:
        current = await asyncio.to_thread(workspace.get, job_id)
        return bool(current and current["status"] == "approved")

    async def on_result(ok: bool, detail) -> None:
        error = None if ok else _FAIL_DETAIL.sub(" ", str((detail or {}).get("error", "")))[:300] or "unknown"

        def apply(state: dict) -> None:
            section = state[artifact]
            section.update(status="sent" if ok else "failed", error=error)
            if artifact == "jira":
                # Keep per-draft results even on failure, so a retry only creates what is missing.
                for sent in payload["drafts"]:
                    if sent.get("result") and sent["index"] < len(section["drafts"]):
                        section["drafts"][sent["index"]]["result"] = sent["result"]
            elif payload.get("result"):
                section["result"] = payload["result"]

        await asyncio.to_thread(workspace.mutate_drafts, job_id, apply)
        created = (", ".join(d["result"]["key"] for d in payload["drafts"] if d.get("result"))
                   if artifact == "jira" else (payload.get("result") or {}).get("title", ""))
        await asyncio.to_thread(audit.record, "publish", "system", job_id=job_id, title=job["title"],
                                detail=f"{artifact} {'sent' if ok else 'failed'}" + (f": {created}" if created else "")
                                + (f" ({error})" if error else ""))

    def queued(state: dict) -> None:
        state[artifact].update(status="queued", error=None)

    await asyncio.to_thread(workspace.mutate_drafts, job_id, queued)
    await asyncio.to_thread(audit.record, "publish_request", requested_by, job_id=job_id, title=job["title"],
                            detail=f"{artifact} queued")
    await enqueue(WriteTask(job_id=job_id, meeting_id=folder, artifact=artifact, payload=payload,
                            base_dir=storage.base_dir, should_send=still_wanted, on_result=on_result))
    return {"status": "queued"}
