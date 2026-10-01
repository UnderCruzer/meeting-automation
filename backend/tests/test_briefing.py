import asyncio
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import auth
from app.routers.workspace import router
from app.services import briefing, write_queue
from app.services.accounts import Accounts
from app.services.audit import AuditLog
from app.services.workspace import Workspace
from app.storage.local import LocalStorage

TODAY = date(2026, 10, 6)  # Tuesday
KST = ZoneInfo("Asia/Seoul")


def _job(id, title, status, decided_at, items, decisions=("결정",)):
    return {"id": id, "title": title, "status": status, "decided_at": decided_at,
            "summary": {"decisions": [{"text": d} for d in decisions],
                        "action_items": [{"description": d, "assignee": a, "due": due, "done": done, "done_at": done_at}
                                         for d, a, due, done, done_at in items]}}


JOBS = [
    _job("a" * 32, "주간 회의", "approved", "2026-10-05 01:00:00", [
        ("보고서 제출", "김민수", "2026-10-02", False, None),   # overdue
        ("QA 공유", "박지은", "2026-10-06", False, None),       # today
        ("배포 준비", "", "2026-10-07", False, None),           # tomorrow
        ("완료된 일", "김민수", "2026-10-01", True, "2026-10-03 02:00:00"),
        ("기한 없음", "김민수", None, False, None),
    ]),
    _job("b" * 32, "검토 중 회의", "review", None, [("미승인 할 일", "x", "2026-10-06", False, None)]),
    _job("c" * 32, "거절된 회의", "rejected", "2026-10-05 01:00:00", [("거절 할 일", "x", "2026-10-06", False, None)]),
]


def test_morning_brief_uses_only_approved_open_tasks(monkeypatch):
    monkeypatch.setenv("SLACK_USER_MAP", "김민수=U0123ABC")
    monkeypatch.setenv("PUBLIC_URL", "https://app.example")
    text = briefing.build_morning_brief(JOBS, TODAY)
    assert "Morning Brief" in text
    assert "보고서 제출 — <@U0123ABC> · 10/2 (4일 지남)" in text
    assert "*🔴 오늘 마감* (1)" in text and "QA 공유 — 박지은" in text
    assert "*🟡 내일 마감* (1)" in text and "배포 준비 — 담당자 미정" in text
    assert "<https://app.example/?meeting=" + "a" * 32 + "|주간 회의>" in text  # approved yesterday (Mon)
    for hidden in ("완료된 일", "미승인 할 일", "거절 할 일", "검토 중 회의", "거절된 회의", "[PERSON"):
        assert hidden not in text


def test_morning_brief_on_friday_looks_to_monday_and_back_to_thursday():
    jobs = [_job("d" * 32, "목요일 회의", "approved", "2026-10-08 05:00:00",
                 [("월요일 마감", "", "2026-10-12", False, None)])]
    text = briefing.build_morning_brief(jobs, date(2026, 10, 9))  # Friday
    assert "다음 근무일 마감" in text and "월요일 마감" in text and "목요일 회의" in text


def test_nothing_to_report_returns_none():
    assert briefing.build_morning_brief([], TODAY) is None
    assert briefing.build_weekly_digest([], TODAY) is None


def test_weekly_digest_counts(monkeypatch):
    monkeypatch.delenv("SLACK_USER_MAP", raising=False)
    text = briefing.build_weekly_digest(JOBS, TODAY)
    assert "회의 1건 승인 · 할 일 5건 생성 · 1건 완료 · 미완료 4건" in text
    assert "결정" in text and "보고서 제출" in text
    assert "• 김민수 2건" in text and "• 담당자 미정 1건" in text


@pytest.mark.parametrize("local,expected", [
    (datetime(2026, 10, 5, 9, 0, tzinfo=KST), ["morning", "weekly"]),   # Monday 09:00
    (datetime(2026, 10, 6, 11, 59, tzinfo=KST), ["morning"]),           # catch-up until noon
    (datetime(2026, 10, 6, 8, 59, tzinfo=KST), []),
    (datetime(2026, 10, 6, 12, 0, tzinfo=KST), []),
    (datetime(2026, 10, 10, 9, 30, tzinfo=KST), []),                    # Saturday
])
def test_schedule_window(monkeypatch, local, expected):
    monkeypatch.delenv("BRIEFING_TIME", raising=False)
    assert briefing.due_briefings(local) == expected


def test_claim_is_once_per_day(tmp_path):
    ws = Workspace(tmp_path)
    assert ws.claim_briefing("morning", "2026-10-06") is True
    assert Workspace(tmp_path).claim_briefing("morning", "2026-10-06") is False
    assert ws.claim_briefing("weekly", "2026-10-06") is True


def test_send_briefing_queues_slack_post(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_BRIEF_CHANNEL", "C0BRIEF")
    monkeypatch.delenv("DIGEST_CHANNEL", raising=False)
    while not write_queue._queue.empty():
        write_queue._queue.get_nowait()
    ws = Workspace(tmp_path)
    ws.create("a" * 32, "주간 회의")
    ws.finish("a" * 32, {"summary_ko": "s", "decisions": [], "quality_flags": [],
                         "action_items": [{"description": "QA 공유", "assignee": "박지은", "due_date": "2026-10-06"}]})
    ws.decide("a" * 32, "approved", "admin")
    sent = asyncio.run(briefing.send_briefing("morning", ws, AuditLog(tmp_path), LocalStorage(tmp_path), TODAY))
    assert sent is True
    task = write_queue._queue.get_nowait()
    assert task.artifact == "slack" and task.payload["suggested_channel"] == "C0BRIEF"
    assert "QA 공유" in task.payload["text"]


def test_admin_preview_and_member_forbidden(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_MODE", "standalone")
    auth._failures.clear()
    app = FastAPI()
    app.state.workspace, app.state.storage, app.state.audit = Workspace(tmp_path), LocalStorage(tmp_path), AuditLog(tmp_path)
    app.state.accounts = Accounts(tmp_path)
    app.state.accounts.create("admin", "correct-horse-battery", role="admin", must_change=False)
    app.state.accounts.create("minsu", "member-pass-1", role="member", must_change=False)
    app.include_router(auth.router)
    app.include_router(router)
    c = TestClient(app)
    login = lambda u, p: {"X-Session-Token": c.post("/auth/login", json={"username": u, "password": p}).json()["token"]}
    res = c.get("/workspace/briefing?kind=weekly", headers=login("admin", "correct-horse-battery"))
    assert res.status_code == 200 and res.json()["kind"] == "weekly" and res.json()["time"] == "09:00"
    assert c.get("/workspace/briefing", headers=login("minsu", "member-pass-1")).status_code == 403
