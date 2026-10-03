"""
Bounded Retrieval — fetch related context from Jira, Confluence, Slack.

Each retriever is bounded to a configured scope (project/space/channel).
Credentials are read from environment variables at call time.
"""
import asyncio
import logging
import os

import httpx

from app.models.analysis import OrchestratorOutput
from app.services import atlassian
from app.models.retrieval import RetrievalContext, RetrievalItem

logger = logging.getLogger(__name__)

# Max items returned per source
_JIRA_MAX = 10
_CONFLUENCE_MAX = 5
_SLACK_MAX = 10


async def retrieve_context(analysis: OrchestratorOutput, sources: list[str] | None = None) -> RetrievalContext:
    """
    Run bounded searches concurrently for each routing target (or the given `sources`).
    Returns a combined RetrievalContext regardless of which sources fail.
    """
    keywords = _build_keywords(analysis)
    terms = _terms(analysis)
    routing = set(analysis.routing if sources is None else sources)

    async with httpx.AsyncClient(timeout=15) as client:
        tasks = {}
        if "jira" in routing:
            tasks["jira"] = _search_jira(client, terms)
        if "confluence" in routing:
            tasks["confluence"] = _search_confluence(client, terms)
        if "slack" in routing:
            tasks["slack"] = _search_slack(client, keywords)

        if not tasks:
            return RetrievalContext(meeting_id=analysis.meeting_id, items=[], sources_searched=[])

        names = list(tasks.keys())
        results = await asyncio.gather(*tasks.values())

    items: list[RetrievalItem] = []
    searched: list[str] = []
    for name, (source_items, ok) in zip(names, results):
        items.extend(source_items)
        if ok:
            searched.append(name)

    return RetrievalContext(
        meeting_id=analysis.meeting_id,
        items=items,
        sources_searched=searched,
    )


def _build_keywords(analysis: OrchestratorOutput) -> str:
    """Combine topics and first action item descriptions into a query string."""
    parts: list[str] = []
    parts.extend(analysis.topics[:3])
    parts.extend(item.description[:60] for item in analysis.action_items[:2])
    # Strip double-quotes so keywords can be safely embedded in JQL/CQL text ~ "..."
    raw = " ".join(parts)[:200]
    return raw.replace('"', "'")


def _terms(analysis: OrchestratorOutput) -> list[str]:
    """Separate terms OR-ed together: one long phrase would require every word to match."""
    return atlassian.search_terms(analysis.topics[:4] + [i.description for i in analysis.action_items[:2]])


async def _search_jira(
    client: httpx.AsyncClient, terms: list[str]
) -> tuple[list[RetrievalItem], bool]:
    site = atlassian.jira_site()
    if site is None:
        logger.debug("[Retrieval] Jira not configured — skipping")
        return [], False
    if not terms:
        return [], True

    # Bounded to the configured project only.
    jql = f'project = "{site.scope}" AND {atlassian.text_clause("text", terms)} ORDER BY updated DESC'
    try:
        resp = await client.post(
            f"{site.base_url}/rest/api/3/search/jql",
            json={"jql": jql, "maxResults": _JIRA_MAX, "fields": ["summary", "description", "status"]},
            headers=site.headers(),
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("[Retrieval] Jira search failed: %s", exc)
        return [], False

    items: list[RetrievalItem] = []
    for issue in data.get("issues", []):
        fields = issue.get("fields", {})
        items.append(RetrievalItem(
            source="jira",
            id=issue["key"],
            title=fields.get("summary", ""),
            url=f"{site.base_url}/browse/{issue['key']}",
            snippet=atlassian.adf_text(fields.get("description")),
            status=(fields.get("status") or {}).get("name", ""),
        ))
    return items, True


async def _search_confluence(
    client: httpx.AsyncClient, terms: list[str]
) -> tuple[list[RetrievalItem], bool]:
    site = atlassian.confluence_site()
    if site is None:
        logger.debug("[Retrieval] Confluence not configured — skipping")
        return [], False
    if not terms:
        return [], True

    # Bounded to the configured space only.
    cql = f'type = "page" AND space = "{site.scope}" AND {atlassian.text_clause("text", terms)} ORDER BY lastmodified DESC'
    try:
        resp = await client.get(
            f"{site.base_url}/wiki/rest/api/search",
            params={"cql": cql, "limit": _CONFLUENCE_MAX},
            headers=site.headers(),
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("[Retrieval] Confluence search failed: %s", exc)
        return [], False

    items: list[RetrievalItem] = []
    for result in data.get("results", []):
        content = result.get("content") or {}
        if not content.get("id"):
            continue
        items.append(RetrievalItem(
            source="confluence",
            id=str(content["id"]),
            title=content.get("title") or atlassian.clean_excerpt(result.get("title", "")),
            url=f"{site.base_url}/wiki{(content.get('_links') or {}).get('webui', '')}",
            snippet=atlassian.clean_excerpt(result.get("excerpt", "")),
        ))
    return items, True


async def _search_slack(
    client: httpx.AsyncClient, keywords: str
) -> tuple[list[RetrievalItem], bool]:
    token = os.getenv("SLACK_BOT_TOKEN", "")
    channel = os.getenv("SLACK_SEARCH_CHANNEL", "")

    if not token:
        logger.debug("[Retrieval] Slack token not configured — skipping")
        return [], False

    query = f"in:#{channel} {keywords}" if channel else keywords
    try:
        resp = await client.get(
            "https://slack.com/api/search.messages",
            params={"query": query, "count": _SLACK_MAX, "sort": "score"},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("error", "Slack API error"))
    except Exception as exc:
        logger.warning("[Retrieval] Slack search failed: %s", exc)
        return [], False

    items: list[RetrievalItem] = []
    for match in data.get("messages", {}).get("matches", []):
        channel_name = match.get("channel", {}).get("name", "")
        ts = match.get("ts", "")
        items.append(RetrievalItem(
            source="slack",
            id=ts,
            title=f"#{channel_name} @ {ts}",
            url=match.get("permalink", ""),
            snippet=match.get("text", "")[:200],
        ))
    return items, True
