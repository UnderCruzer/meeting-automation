"""Atlassian connection helpers: configuration, bounded search terms, ADF."""
import httpx
import pytest

from app.services import atlassian

SITE = {"ATLASSIAN_BASE_URL": "https://team.atlassian.net/", "ATLASSIAN_EMAIL": "me@example.com",
        "ATLASSIAN_API_TOKEN": "test-token"}


@pytest.fixture
def clean_env(monkeypatch):
    for prefix in ("ATLASSIAN", "JIRA", "CONFLUENCE"):
        for name in ("BASE_URL", "EMAIL", "API_TOKEN"):
            monkeypatch.delenv(f"{prefix}_{name}", raising=False)
    monkeypatch.delenv("JIRA_PROJECT_KEY", raising=False)
    monkeypatch.delenv("CONFLUENCE_SPACE_KEY", raising=False)
    return monkeypatch


def test_shared_site_serves_both_products(clean_env):
    for key, value in SITE.items():
        clean_env.setenv(key, value)
    clean_env.setenv("JIRA_PROJECT_KEY", "team")
    clean_env.setenv("CONFLUENCE_SPACE_KEY", "DOC")
    jira, confluence = atlassian.jira_site(), atlassian.confluence_site()
    assert jira.base_url == "https://team.atlassian.net" and jira.scope == "TEAM"
    assert confluence.scope == "DOC" and confluence.token == "test-token"
    assert jira.headers()["Authorization"].startswith("Basic ")


def test_product_settings_override_shared_ones(clean_env):
    for key, value in SITE.items():
        clean_env.setenv(key, value)
    clean_env.setenv("JIRA_PROJECT_KEY", "OPS")
    clean_env.setenv("JIRA_BASE_URL", "https://other.atlassian.net")
    assert atlassian.jira_site().base_url == "https://other.atlassian.net"


@pytest.mark.parametrize("override", [
    {"JIRA_PROJECT_KEY": ""},                       # no project → nothing to bound the search to
    {"JIRA_PROJECT_KEY": 'X" OR project != "X'},    # not a project key (JQL injection)
    {"ATLASSIAN_API_TOKEN": ""},
    {"ATLASSIAN_BASE_URL": "http://team.atlassian.net"},  # credentials only over HTTPS
])
def test_incomplete_or_unsafe_settings_disable_the_product(clean_env, override):
    for key, value in {**SITE, "JIRA_PROJECT_KEY": "OPS", **override}.items():
        clean_env.setenv(key, value)
    assert atlassian.jira_site() is None


def test_search_terms_drop_masking_tokens_and_query_syntax():
    terms = atlassian.search_terms(['[PERSON_1] 님과 "배포" 일정', "API-설계 (v2)", "[MASKED_EMAIL]", "API 설계 v2"])
    assert terms == ["님과 배포 일정", "API 설계 v2"]
    assert all('"' not in t and "PERSON" not in t for t in terms)


def test_text_clause_ors_terms():
    assert atlassian.text_clause("text", ["a b", "c"]) == '(text ~ "a b" OR text ~ "c")'


def test_issue_keys_are_bounded_to_the_project():
    assert atlassian.valid_issue_key("OPS-12", "OPS")
    assert not atlassian.valid_issue_key("HR-3", "OPS")
    assert not atlassian.valid_issue_key("OPS-12/comment", "OPS")


def test_plain_text_becomes_adf_paragraphs_and_bullets():
    doc = atlassian.to_adf("배경\n\n- 첫째\n- 둘째\n끝")
    assert [n["type"] for n in doc["content"]] == ["paragraph", "bulletList", "paragraph"]
    assert len(doc["content"][1]["content"]) == 2
    assert atlassian.adf_text(doc) == "배경 첫째 둘째 끝"
    assert atlassian.to_adf("")["content"]  # Jira rejects an empty document


def test_error_messages_from_jira_and_confluence():
    jira = httpx.Response(400, json={"errorMessages": [], "errors": {"priority": "Field 'priority' cannot be set."}})
    confluence = httpx.Response(400, json={"errors": [{"status": 400, "title": "A page with this title already exists"}]})
    assert atlassian.error_fields(jira) == {"priority"}
    assert atlassian.error_fields(confluence) == set()
    assert "cannot be set" in atlassian.error_message(jira)
    assert "already exists" in atlassian.error_message(confluence)
    assert atlassian.error_message(httpx.Response(502, text="bad gateway")) == "HTTP 502"
