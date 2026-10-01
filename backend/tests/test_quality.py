import asyncio
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import auth
from app.routers.workspace import router
from app.services import quality, write_queue
from app.services.accounts import Accounts
from app.services.audit import AuditLog
from app.services.workspace import Workspace
from app.storage.local import LocalStorage

TODAY = date(2026, 10, 6)


def _job(id, status, created, finished=None, decided=None, error=None, confidence=None, items=(), publish=None, flags=()):
    return {"id": id, "status": status, "created_at": created, "finished_at": finished, "decided_at": decided,
            "error_code": error, "confidence": confidence, "quality_ok": None, "publish_status": publish,
            "summary": {"action_items": list(items), "quality_flags": list(flags)} if status != "failed" else None}


JOBS = [
    _job("a", "approved", "2026-10-05 01:00:00", "2026-10-05 01:04:00", "2026-10-05 02:04:00", confidence=0.9,
         items=[{"done": True}, {"done": False, "due": "2026-10-01"}], publish="sent"),
    _job("b", "rejected", "2026-10-05 03:00:00", "2026-10-05 03:02:00", "2026-10-05 03:32:00", confidence=0.5,
         flags=[{"message": "짧음"}]),
    _job("c", "review", "2026-10-05 04:00:00", "2026-10-05 04:06:00", confidence=0.7),
    _job("d", "failed", "2026-10-05 05:00:00", "2026-10-05 05:01:00", error="LLM_BUSY"),
    _job("e", "processing", "2026-10-05 06:00:00"),
]
FEEDBACK = [{"rating": "good", "categories": []},
            {"rating": "bad", "categories": ["owner_wrong", "citation_wrong"]},
            {"rating": "bad", "categories": ["owner_wrong"]}]
EVENTS = [{"action": "edit", "job_id": "a"}, {"action": "edit", "job_id": "c"}]


def test_metrics_from_pipeline_outcomes():
    m = quality.compute_metrics(JOBS, FEEDBACK, EVENTS, TODAY)
    assert (m["uploads"], m["processing"], m["succeeded"], m["failed"]) == (5, 1, 3, 1)
    assert m["success_rate"] == 0.75
    assert m["failures"] == [{"code": "LLM_BUSY", "label": "AI 서비스 혼잡", "count": 1}]
    assert m["median_processing_minutes"] == 3.0          # 4, 2, 6, 1 minutes → median 3
    assert (m["approved"], m["rejected"], m["pending_review"], m["approval_rate"]) == (1, 1, 1, 0.5)
    assert m["median_minutes_to_decision"] == 45.0        # 60 and 30 minutes
    assert m["edited_before_decision_rate"] == 0.5        # a edited, b not (c not decided)
    assert (m["action_items_per_meeting"], m["task_completion_rate"], m["tasks_overdue"]) == (2.0, 0.5, 1)
    assert m["avg_confidence"] == 0.7 and m["low_quality"] == 1
    assert (m["feedback"], m["positive_feedback_rate"]) == (3, 0.3333)
    assert m["feedback_categories"][0] == {"code": "owner_wrong", "label": "담당자·기한 오류", "count": 2}
    assert m["slack_publish_rate"] == 1.0


def test_empty_window_has_no_ratios():
    m = quality.compute_metrics([], [], [], TODAY)
    assert m["uploads"] == 0 and m["success_rate"] is None and m["avg_confidence"] is None


def test_anomalies_need_enough_samples(monkeypatch):
    monkeypatch.delenv("ALERT_FAILURE_RATE", raising=False)
    monkeypatch.delenv("ALERT_MIN_CONFIDENCE", raising=False)
    busy = [_job(str(i), "failed", "2026-10-05 05:00:00", "2026-10-05 05:01:00", error="LLM_BUSY") for i in range(3)]
    day = quality.compute_metrics(busy + JOBS[:1], [], [], TODAY)
    week = quality.compute_metrics(JOBS, FEEDBACK, [], TODAY)
    codes = [a["code"] for a in quality.detect_anomalies(day, week)]
    assert codes == ["failure_rate", "llm_busy", "negative_feedback"]
    quiet = quality.compute_metrics(JOBS[:2], FEEDBACK[:1], [], TODAY)
    assert quality.detect_anomalies(quiet, quiet) == []


def test_weekly_report_text():
    text = quality.weekly_report_text(quality.compute_metrics(JOBS, FEEDBACK, EVENTS, TODAY), TODAY)
    assert "주간 품질 리포트" in text and "처리 성공률 75%" in text and "AI 서비스 혼잡 1" in text
    assert "담당자·기한 오류 2" in text


def _app(tmp_path, monkeypatch):
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
    return app, c, login


def test_feedback_upsert_rules_and_removal(tmp_path, monkeypatch):
    app, c, login = _app(tmp_path, monkeypatch)
    member = login("minsu", "member-pass-1")
    ws = app.state.workspace
    ws.create("j" * 32, "회의")
    url = f"/workspace/jobs/{'j' * 32}/feedback"
    assert c.post(url, json={"rating": "good"}, headers=member).status_code == 409   # still processing
    ws.finish("j" * 32, {"summary_ko": "s", "action_items": [], "decisions": [], "quality_flags": [], "quality_ok": True}, 0.82)
    assert ws.get("j" * 32)["confidence"] == 0.82 and ws.get("j" * 32)["finished_at"]
    assert c.post(url, json={"rating": "bad", "categories": ["owner_wrong", "owner_wrong"], "note": " 담당자 틀림 "},
                  headers=member).status_code == 200
    assert c.post(url, json={"rating": "bad", "categories": ["nope"]}, headers=member).status_code == 422
    got = c.get(url, headers=member).json()
    assert got == {"mine": {"rating": "bad", "categories": ["owner_wrong"], "note": "담당자 틀림"}, "good": 0, "bad": 1}
    c.post(url, json={"rating": "good", "categories": ["other"]}, headers=member)       # change of mind, categories dropped
    assert c.get(url, headers=member).json()["mine"] == {"rating": "good", "categories": [], "note": ""}
    assert app.state.audit.recent()[0]["action"] == "feedback"
    c.post(f"/workspace/jobs/{'j' * 32}/decision", json={"status": "rejected"}, headers=member)
    c.delete(f"/workspace/jobs/{'j' * 32}", headers=member)
    assert ws.feedback_for("j" * 32) == []


def test_metrics_endpoint_admin_only(tmp_path, monkeypatch):
    _, c, login = _app(tmp_path, monkeypatch)
    res = c.get("/workspace/metrics?days=30", headers=login("admin", "correct-horse-battery"))
    assert res.status_code == 200 and res.json()["days"] == 30 and res.json()["metrics"]["uploads"] == 0
    assert c.get("/workspace/metrics", headers=login("minsu", "member-pass-1")).status_code == 403
    assert c.get("/workspace/metrics?days=3", headers=login("admin", "correct-horse-battery")).status_code == 422


def test_quality_checks_alert_once_per_day(tmp_path, monkeypatch):
    monkeypatch.setenv("MONITOR_ALERT_CHANNEL", "C0ADMIN")
    while not write_queue._queue.empty():
        write_queue._queue.get_nowait()
    ws, audit, storage = Workspace(tmp_path), AuditLog(tmp_path), LocalStorage(tmp_path)
    for i in range(3):
        ws.create(f"{i:032x}", "회의")
        ws.fail(f"{i:032x}", "LLM_BUSY")
    today = date.today()
    first = asyncio.run(quality.run_quality_checks(ws, audit, storage, today, weekly=True))
    assert {a["code"] for a in first} == {"failure_rate", "llm_busy"}
    texts = [write_queue._queue.get_nowait().payload for _ in range(3)]
    assert {t["suggested_channel"] for t in texts} == {"C0ADMIN"}
    assert any("주간 품질 리포트" in t["text"] for t in texts)
    asyncio.run(quality.run_quality_checks(ws, audit, storage, today, weekly=True))
    assert write_queue._queue.empty()   # same day: nothing re-sent


def test_quality_checks_need_admin_channel(tmp_path, monkeypatch):
    monkeypatch.delenv("MONITOR_ALERT_CHANNEL", raising=False)
    ws = Workspace(tmp_path)
    assert asyncio.run(quality.run_quality_checks(ws, AuditLog(tmp_path), LocalStorage(tmp_path), TODAY, True)) == []
