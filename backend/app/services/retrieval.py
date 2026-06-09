"""
Bounded Retrieval — fetch related context from Jira, Confluence, Slack.

Each retriever is bounded to a configured scope (project/space/channel).
Credentials are read from environment variables at call time.
"""
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
    Run bounded searches for each routing target in the analysis.
    Returns a combined RetrievalContext regardless of which sources fail.
    """
    keywords = _build_keywords(analysis)
    routing = set(analysis.routing)
    items: list[RetrievalItem] = []
    searched: list[str] = []

    async with httpx.AsyncClient(timeout=15) as client:
        if "jira" in routing:
            results, ok = await _search_jira(client, keywords)
            items.extend(results)
            if ok:
                searched.append("jira")

        if "confluence" in routing:
            results, ok = await _search_confluence(client, keywords)
            items.extend(results)
            if ok:
                searched.append("confluence")

        if "slack" in routing:
            results, ok = await _search_slack(client, keywords)
            items.extend(results)
            if ok:
                searched.append("slack")

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
    return " ".join(parts)[:200]  # Jira/Confluence JQL text limit


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
        resp = await client.get(
            f"{base_url}/rest/api/3/search",
            params={"jql": jql, "maxResults": _JIRA_MAX, "fields": "summary,description,status"},
            headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
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
