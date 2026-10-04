"""Atlassian Cloud (Jira, Confluence) connection — workflow 10 (search), 12·13 (create after approval).

One Atlassian site usually serves both products with one API token, so ATLASSIAN_* is shared and
JIRA_* / CONFLUENCE_* override it per product. A product is enabled only when its site, e-mail,
token and scope (Jira project / Confluence space) are all set — searches and writes never leave
that project or space.
"""
from __future__ import annotations

import os
import re
from base64 import b64encode
from dataclasses import dataclass
from html import unescape

import httpx

_KEY = re.compile(r"[A-Z][A-Z0-9_]{1,9}")
_ISSUE_KEY = re.compile(r"[A-Z][A-Z0-9_]{1,9}-\d{1,7}")
# Masking tokens and characters that are operators in Jira/Confluence text search.
_TOKENS = re.compile(r"\[(?:PERSON_\d+|MASKED_[A-Z_]+)\]")
_SEARCH_SYNTAX = re.compile(r"[\"\\+\-&|!(){}\[\]^~*?:/]")
# Fields some Jira project types don't have on their create screen; dropped on a 400 for them.
OPTIONAL_JIRA_FIELDS = ("priority", "labels")
LABEL = "meeting-automation"


@dataclass(frozen=True)
class Site:
    base_url: str
    email: str
    token: str
    scope: str  # Jira project key or Confluence space key

    def headers(self) -> dict[str, str]:
        auth = b64encode(f"{self.email}:{self.token}".encode()).decode()
        return {"Authorization": f"Basic {auth}", "Accept": "application/json", "Content-Type": "application/json"}


def _site(prefix: str, scope_env: str) -> Site | None:
    def get(name: str) -> str:
        return (os.getenv(f"{prefix}_{name}") or os.getenv(f"ATLASSIAN_{name}") or "").strip()

    base_url, scope = get("BASE_URL").rstrip("/"), (os.getenv(scope_env) or "").strip().upper()
    site = Site(base_url, get("EMAIL"), get("API_TOKEN"), scope)
    if not (base_url.startswith("https://") and site.email and site.token and _KEY.fullmatch(scope)):
        return None
    return site


def jira_site() -> Site | None:
    return _site("JIRA", "JIRA_PROJECT_KEY")


def confluence_site() -> Site | None:
    return _site("CONFLUENCE", "CONFLUENCE_SPACE_KEY")


def jira_issue_type() -> str:
    return os.getenv("JIRA_ISSUE_TYPE", "").strip() or "Task"


def valid_issue_key(key: str, project: str) -> bool:
    """Only issues of the configured project may be commented on."""
    return bool(_ISSUE_KEY.fullmatch(key or "")) and key.startswith(f"{project}-")


def search_terms(phrases: list[str], limit: int = 5) -> list[str]:
    """Short, operator-free search terms from topics / action items (masking tokens removed)."""
    terms: list[str] = []
    for phrase in phrases:
        text = _SEARCH_SYNTAX.sub(" ", _TOKENS.sub(" ", phrase or ""))
        text = " ".join(text.split())[:40].strip()
        if len(text) >= 2 and text not in terms:
            terms.append(text)
        if len(terms) == limit:
            break
    return terms


def text_clause(field: str, terms: list[str]) -> str:
    """`(text ~ "a" OR text ~ "b")` — terms are already free of quotes and operators."""
    return "(" + " OR ".join(f'{field} ~ "{t}"' for t in terms) + ")"


def to_adf(text: str) -> dict:
    """Plain text → Atlassian Document Format: blank-line paragraphs, "- " lines as bullets."""
    content: list[dict] = []
    bullets: list[dict] = []

    def flush() -> None:
        if bullets:
            content.append({"type": "bulletList", "content": list(bullets)})
            bullets.clear()

    for line in (text or "").splitlines():
        line = line.rstrip()
        if line.lstrip().startswith(("- ", "* ", "• ")):
            item = line.lstrip()[2:].strip()
            if item:
                bullets.append({"type": "listItem", "content": [_paragraph(item)]})
            continue
        flush()
        if line.strip():
            content.append(_paragraph(line.strip()))
    flush()
    return {"type": "doc", "version": 1, "content": content or [_paragraph("-")]}


def _paragraph(text: str) -> dict:
    return {"type": "paragraph", "content": [{"type": "text", "text": text[:30000]}]}


def adf_text(node, limit: int = 200) -> str:
    """Flatten an ADF document (Jira descriptions) to plain text."""
    if isinstance(node, str):
        return " ".join(node.split())[:limit]
    parts: list[str] = []

    def walk(n) -> None:
        if isinstance(n, dict):
            if n.get("type") == "text":
                parts.append(n.get("text", ""))
            for child in n.get("content", []) or []:
                walk(child)
        elif isinstance(n, list):
            for child in n:
                walk(child)

    walk(node)
    return " ".join(" ".join(parts).split())[:limit]


def clean_excerpt(text: str, limit: int = 200) -> str:
    """Confluence search excerpts carry @@@hl@@@ highlight markers and HTML entities."""
    text = re.sub(r"@@@(?:end)?hl@@@", "", text or "")
    text = unescape(re.sub(r"<[^>]+>", "", text))
    return " ".join(text.split())[:limit]


def error_fields(res: httpx.Response) -> set[str]:
    """Field names Jira rejected in a 400 response ({"errors": {"priority": "..."}})."""
    try:
        errors = (res.json() or {}).get("errors")
    except (ValueError, AttributeError):
        return set()
    return set(errors) if isinstance(errors, dict) else set()


def error_message(res: httpx.Response) -> str:
    if res.status_code in (401, 403):
        return f"인증 실패(HTTP {res.status_code}) — 이메일·API 토큰과 프로젝트·스페이스 권한을 확인하세요"
    return _body_message(res)


def _body_message(res: httpx.Response) -> str:
    """Readable reason from Jira ({"errorMessages", "errors": {...}}) or Confluence v2 ({"errors": [...]})."""
    try:
        body = res.json() or {}
        errors = body.get("errors") or {}
    except (ValueError, AttributeError):
        return f"HTTP {res.status_code}"
    messages = [str(m) for m in body.get("errorMessages", []) or []]
    if isinstance(errors, dict):
        messages += [str(v) for v in errors.values()]
    else:
        messages += [str(e.get("title") or e.get("detail") or e) for e in errors if isinstance(e, dict)]
    if body.get("message"):
        messages.append(str(body["message"]))
    return "; ".join(messages)[:300] or f"HTTP {res.status_code}"


UNREACHABLE = "Atlassian 사이트에 연결하지 못했습니다 — ATLASSIAN_BASE_URL 주소를 확인하세요"
