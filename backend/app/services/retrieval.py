"""
Bounded Retrieval — fetch related context from Jira, Confluence, Slack.

Each retriever is bounded to a configured scope (project/space/channel).
Credentials are read from environment variables at call time.
"""
import asyncio
import logging
import os
from base64 import b64encode

import httpx

from app.models.analysis import OrchestratorOutput
from app.models.retrieval import RetrievalContext, RetrievalItem

logger = logging.getLogger(__name__)

# Max items returned per source
_JIRA_MAX = 10
_CONFLUENCE_MAX = 5
_SLACK_MAX = 10


async def retrieve_context(analysis: OrchestratorOutput) -> RetrievalContext:
    """
    Run bounded searches concurrently for each routing target.
    Returns a combined RetrievalContext regardless of which sources fail.
    """
    keywords = _build_keywords(analysis)
    routing = set(analysis.routing)

    async with httpx.AsyncClient(timeout=15) as client:
        tasks = {}
        if "jira" in routing:
            tasks["jira"] = _search_jira(client, keywords)
        if "confluence" in routing:
            tasks["confluence"] = _search_confluence(client, keywords)
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


async def _search_jira(
    client: httpx.AsyncClient, keywords: str
) -> tuple[list[RetrievalItem], bool]:
    base_url = os.getenv("JIRA_BASE_URL", "").rstrip("/")
    project = os.getenv("JIRA_PROJECT_KEY", "")
    token = os.getenv("JIRA_API_TOKEN", "")
    email = os.getenv("JIRA_EMAIL", "")

    if not all([base_url, project, token, email]):
        logger.debug("[Retrieval] Jira credentials not configured — skipping")
        return [], False

    auth = b64encode(f"{email}:{token}".encode()).decode()
    jql = f'project = "{project}" AND text ~ "{keywords}" ORDER BY updated DESC'
    try:
        resp = await client.post(
            f"{base_url}/rest/api/3/search",
            json={"jql": jql, "maxResults": _JIRA_MAX, "fields": ["summary", "description", "status"]},
            headers={"Authorization": f"Basic {auth}", "Accept": "application/json", "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("[Retrieval] Jira search failed: %s", exc)
        return [], False

    items: list[RetrievalItem] = []
    for issue in data.get("issues", []):
        fields = issue.get("fields", {})
        desc = fields.get("description") or ""
        snippet = str(desc)[:200] if desc else ""
        items.append(RetrievalItem(
            source="jira",
            id=issue["key"],
            title=fields.get("summary", ""),
            url=f"{base_url}/browse/{issue['key']}",
            snippet=snippet,
        ))
    return items, True


async def _search_confluence(
    client: httpx.AsyncClient, keywords: str
) -> tuple[list[RetrievalItem], bool]:
    base_url = os.getenv("CONFLUENCE_BASE_URL", "").rstrip("/")
    space = os.getenv("CONFLUENCE_SPACE_KEY", "")
    token = os.getenv("CONFLUENCE_API_TOKEN", "")
    email = os.getenv("CONFLUENCE_EMAIL", "")

    if not all([base_url, space, token, email]):
        logger.debug("[Retrieval] Confluence credentials not configured — skipping")
        return [], False

    auth = b64encode(f"{email}:{token}".encode()).decode()
    cql = f'type = "page" AND space = "{space}" AND text ~ "{keywords}" ORDER BY lastModified DESC'
    try:
        resp = await client.get(
            f"{base_url}/rest/api/content/search",
            params={"cql": cql, "limit": _CONFLUENCE_MAX, "expand": "excerpt"},
            headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("[Retrieval] Confluence search failed: %s", exc)
        return [], False

    items: list[RetrievalItem] = []
    for page in data.get("results", []):
        items.append(RetrievalItem(
            source="confluence",
            id=page["id"],
            title=page.get("title", ""),
            url=f"{base_url}{page.get('_links', {}).get('webui', '')}",
            snippet=page.get("excerpt", "")[:200],
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
