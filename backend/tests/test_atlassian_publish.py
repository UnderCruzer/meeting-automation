"""Write Queue → Jira issues / Confluence page after approval (workflow 12·13)."""
import asyncio
import json

import httpx
import pytest

from app.services import write_queue

_real_client = httpx.AsyncClient


@pytest.fixture
def atlassian_env(monkeypatch):
    monkeypatch.setenv("ATLASSIAN_BASE_URL", "https://team.atlassian.net")
    monkeypatch.setenv("ATLASSIAN_EMAIL", "me@example.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "test-token")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "OPS")
    monkeypatch.setenv("CONFLUENCE_SPACE_KEY", "DOC")
    for name in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "CONFLUENCE_BASE_URL", "CONFLUENCE_EMAIL",
                 "CONFLUENCE_API_TOKEN", "JIRA_ISSUE_TYPE"):
        monkeypatch.delenv(name, raising=False)


def _serve(monkeypatch, handler):
    calls = []

    def record(request):
        calls.append(request)
        return handler(request, len(calls))

    monkeypatch.setattr(write_queue.httpx, "AsyncClient",
                        lambda **kw: _real_client(transport=httpx.MockTransport(record), **kw))
    return calls


def _drafts():
    return {"drafts": [
        {"action": "create", "summary": "릴리스 노트 작성", "description": "담당: 김민수\n- 변경점 정리", "priority": "High"},
        {"action": "create", "summary": "QA 일정 공유", "description": "금요일까지", "priority": "Medium"},
    ]}


def test_creates_issues_in_the_project_with_adf_and_label(atlassian_env, monkeypatch):
    keys = iter(["OPS-7", "OPS-8"])
    calls = _serve(monkeypatch, lambda req, n: httpx.Response(201, json={"key": next(keys)}))
    result = asyncio.run(write_queue._publish_jira(_drafts()))
    assert [r["key"] for r in result["results"]] == ["OPS-7", "OPS-8"]
    assert result["results"][0]["url"] == "https://team.atlassian.net/browse/OPS-7"
    fields = json.loads(calls[0].content)["fields"]
    assert fields["project"] == {"key": "OPS"} and fields["issuetype"] == {"name": "Task"}
    assert fields["labels"] == ["meeting-automation"] and fields["priority"] == {"name": "High"}
    assert fields["description"]["content"][1]["type"] == "bulletList"
    assert calls[0].headers["Authorization"].startswith("Basic ")


def test_retry_after_partial_failure_does_not_duplicate_issues(atlassian_env, monkeypatch):
    payload = _drafts()
    created = []

    def jira(req, n):
        if n == 2:
            return httpx.Response(503, json={"errorMessages": ["busy"]})
        created.append(json.loads(req.content)["fields"]["summary"])
        return httpx.Response(201, json={"key": f"OPS-{len(created)}"})

    _serve(monkeypatch, jira)
    with pytest.raises(RuntimeError, match="busy"):
        asyncio.run(write_queue._publish_jira(payload))
    result = asyncio.run(write_queue._publish_jira(payload))   # what the queue's next attempt does
    assert created == ["릴리스 노트 작성", "QA 일정 공유"]
    assert [r["key"] for r in result["results"]] == ["OPS-1", "OPS-2"]


def test_fields_missing_from_the_project_are_dropped(atlassian_env, monkeypatch):
    def jira(req, n):
        fields = json.loads(req.content)["fields"]
        if "priority" in fields:
            return httpx.Response(400, json={"errors": {"priority": "Field 'priority' cannot be set."}})
        return httpx.Response(201, json={"key": "OPS-1"})

    calls = _serve(monkeypatch, jira)
    result = asyncio.run(write_queue._publish_jira({"drafts": _drafts()["drafts"][:1]}))
    assert result["results"][0]["key"] == "OPS-1"
    assert "labels" in json.loads(calls[1].content)["fields"]


def test_comments_only_on_issues_of_the_project(atlassian_env, monkeypatch):
    calls = _serve(monkeypatch, lambda req, n: httpx.Response(201, json={"id": "1"}))
    ok = asyncio.run(write_queue._publish_jira({"drafts": [
        {"action": "comment", "existing_key": "OPS-3", "summary": "", "description": "회의에서 일정 확정"}]}))
    assert ok["results"][0] == {"action": "commented", "key": "OPS-3", "url": "https://team.atlassian.net/browse/OPS-3"}
    assert calls[0].url.path == "/rest/api/3/issue/OPS-3/comment"
    with pytest.raises(RuntimeError, match="outside project"):
        asyncio.run(write_queue._publish_jira({"drafts": [
            {"action": "comment", "existing_key": "HR-1", "summary": "", "description": "x"}]}))
    assert len(calls) == 1


def _confluence(page_status=200, titles_taken=()):
    def handler(req, n):
        if req.url.path == "/wiki/api/v2/spaces":
            assert req.url.params["keys"] == "DOC"
            return httpx.Response(200, json={"results": [{"id": "98", "key": "DOC"}]})
        body = json.loads(req.content)
        if body["title"] in titles_taken:
            return httpx.Response(400, json={"errors": [{"status": 400, "title": "A page with this title already exists"}]})
        return httpx.Response(page_status, json={"id": "555", "title": body["title"],
                                                 "_links": {"base": "https://team.atlassian.net/wiki",
                                                            "webui": "/spaces/DOC/pages/555"}})
    return handler


PAGE = {"title": "회의록 2026-10-03 — 출시 회의", "body": "<p>요약</p>", "suffix": "0123ab"}


def test_creates_minutes_page_in_the_space(atlassian_env, monkeypatch):
    calls = _serve(monkeypatch, _confluence())
    result = asyncio.run(write_queue._publish_confluence(dict(PAGE)))
    assert result["url"] == "https://team.atlassian.net/wiki/spaces/DOC/pages/555"
    body = json.loads(calls[1].content)
    assert body["spaceId"] == "98" and body["body"] == {"representation": "storage", "value": "<p>요약</p>"}
    assert "parentId" not in body
    asyncio.run(write_queue._publish_confluence({**PAGE, "parent_page_id": "4100"}))
    assert json.loads(calls[3].content)["parentId"] == "4100"


def test_same_title_gets_a_suffix_and_retry_reuses_the_page(atlassian_env, monkeypatch):
    payload = dict(PAGE)
    calls = _serve(monkeypatch, _confluence(titles_taken={PAGE["title"]}))
    result = asyncio.run(write_queue._publish_confluence(payload))
    assert result["title"] == "회의록 2026-10-03 — 출시 회의 (0123ab)"
    asyncio.run(write_queue._publish_confluence(payload))
    assert len(calls) == 3   # spaces + 2 create attempts; the second call returned the stored page


def test_unknown_space_fails_clearly(atlassian_env, monkeypatch):
    _serve(monkeypatch, lambda req, n: httpx.Response(200, json={"results": []}))
    with pytest.raises(RuntimeError, match="space DOC not found"):
        asyncio.run(write_queue._publish_confluence(dict(PAGE)))


def test_not_configured_raises(monkeypatch):
    monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="not configured"):
        asyncio.run(write_queue._publish_jira(_drafts()))


def test_unreachable_site_and_bad_token_read_clearly(atlassian_env, monkeypatch, tmp_path):
    from app.services import atlassian

    def down(request):
        raise httpx.ConnectError("[Errno -2] Name or service not known")

    monkeypatch.setattr(write_queue.httpx, "AsyncClient",
                        lambda **kw: _real_client(transport=httpx.MockTransport(down), **kw))
    real_sleep = asyncio.sleep
    monkeypatch.setattr(write_queue.asyncio, "sleep", lambda seconds: real_sleep(0))   # skip retry backoff
    results = []

    async def on_result(ok, detail):
        results.append((ok, detail))

    task = write_queue.WriteTask(job_id="j", meeting_id="m", artifact="jira", payload=_drafts(), base_dir=tmp_path,
                                 on_result=on_result)
    asyncio.run(write_queue._dispatch(task))
    assert results == [(False, {"error": atlassian.UNREACHABLE})]
    assert "인증 실패" in atlassian.error_message(httpx.Response(401, text="Unauthorized"))
