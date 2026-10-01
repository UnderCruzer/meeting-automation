"""Workflow 22: quality metrics, anomaly alerts and the weekly quality report.

Everything is computed from the workspace database (jobs, feedback) and the audit log —
the real pipeline outcomes, not write-queue attempts. Alerts and the weekly report go to
MONITOR_ALERT_CHANNEL (an admin channel), never to the team channel.
"""
from __future__ import annotations

import asyncio
import os
import statistics
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from app.services.write_queue import WriteTask, enqueue

FEEDBACK_CATEGORIES = {
    "summary_missing": "요약 누락·왜곡",
    "action_missing": "할 일 누락",
    "owner_wrong": "담당자·기한 오류",
    "citation_wrong": "근거 부정확",
    "other": "기타",
}
FAILURE_LABELS = {
    "LLM_BUSY": "AI 서비스 혼잡", "ANALYSIS_FAILED": "AI 분석 실패", "STT_FAILED": "전사 실패",
    "NO_SPEECH": "음성 없음", "RESTARTED": "서버 재시작", "FAILED": "기타 실패",
}


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _median_minutes(deltas: list[timedelta]) -> float | None:
    values = [d.total_seconds() / 60 for d in deltas if d.total_seconds() >= 0]
    return round(statistics.median(values), 1) if values else None


def since_utc(days: int, now: datetime | None = None) -> str:
    moment = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def compute_metrics(jobs: list[dict], feedback: list[dict], audit_events: list[dict], today: date) -> dict:
    """Pure function over the window's rows (see Workspace.metrics_rows)."""
    finished = [j for j in jobs if j["status"] != "processing"]
    succeeded = [j for j in finished if j["status"] != "failed"]
    failed = [j for j in finished if j["status"] == "failed"]
    decided = [j for j in succeeded if j["status"] in ("approved", "rejected")]
    approved = [j for j in decided if j["status"] == "approved"]

    processing_times = [_ts(j.get("finished_at")) - _ts(j.get("created_at")) for j in finished
                        if _ts(j.get("finished_at")) and _ts(j.get("created_at"))]
    decision_times = [_ts(j.get("decided_at")) - _ts(j.get("finished_at")) for j in decided
                      if _ts(j.get("decided_at")) and _ts(j.get("finished_at"))]
    edited_ids = {e.get("job_id") for e in audit_events if e.get("action") == "edit"}

    items = [i for j in approved for i in (j.get("summary") or {}).get("action_items", [])]
    done = [i for i in items if i.get("done")]
    overdue = [i for i in items if not i.get("done") and i.get("due") and date.fromisoformat(i["due"]) < today]

    confidences = [j["confidence"] for j in succeeded if isinstance(j.get("confidence"), (int, float))]
    low_quality = [j for j in succeeded if j.get("quality_ok") == 0
                   or (j.get("summary") or {}).get("quality_flags")]

    published = [j for j in approved if j.get("publish_status") in ("sent", "failed")]
    good = [f for f in feedback if f["rating"] == "good"]
    categories = Counter(c for f in feedback if f["rating"] == "bad" for c in f.get("categories", []))

    return {
        "uploads": len(jobs),
        "processing": len(jobs) - len(finished),
        "succeeded": len(succeeded),
        "failed": len(failed),
        "success_rate": _ratio(len(succeeded), len(finished)),
        "failures": [{"code": c, "label": FAILURE_LABELS.get(c, c), "count": n}
                     for c, n in Counter(j.get("error_code") or "FAILED" for j in failed).most_common()],
        "median_processing_minutes": _median_minutes(processing_times),
        "pending_review": sum(1 for j in succeeded if j["status"] == "review"),
        "approved": len(approved),
        "rejected": len(decided) - len(approved),
        "approval_rate": _ratio(len(approved), len(decided)),
        "median_minutes_to_decision": _median_minutes(decision_times),
        "edited_before_decision_rate": _ratio(sum(1 for j in decided if j["id"] in edited_ids), len(decided)),
        "action_items_per_meeting": round(len(items) / len(approved), 2) if approved else None,
        "task_completion_rate": _ratio(len(done), len(items)),
        "tasks_overdue": len(overdue),
        "avg_confidence": round(sum(confidences) / len(confidences), 3) if confidences else None,
        "low_quality": len(low_quality),
        "feedback": len(feedback),
        "positive_feedback_rate": _ratio(len(good), len(feedback)),
        "feedback_categories": [{"code": c, "label": FEEDBACK_CATEGORIES.get(c, c), "count": n}
                                for c, n in categories.most_common()],
        "slack_publish_rate": _ratio(sum(1 for j in published if j["publish_status"] == "sent"), len(published)),
    }


def _threshold(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def detect_anomalies(day_metrics: dict, week_metrics: dict) -> list[dict]:
    """Warnings for the last 24 h (failures) and 7 days (feedback, confidence). Small samples are ignored."""
    alerts = []
    finished_day = day_metrics["succeeded"] + day_metrics["failed"]
    fail_limit = _threshold("ALERT_FAILURE_RATE", 0.3)
    if finished_day >= 3 and day_metrics["failed"] / finished_day >= fail_limit:
        alerts.append({"code": "failure_rate", "message":
                       f"최근 24시간 처리 실패율 {day_metrics['failed'] / finished_day:.0%} "
                       f"({day_metrics['failed']}/{finished_day}건, 기준 {fail_limit:.0%})"})
    busy = next((f["count"] for f in day_metrics["failures"] if f["code"] == "LLM_BUSY"), 0)
    if busy >= 3:
        alerts.append({"code": "llm_busy", "message":
                       f"최근 24시간 AI 서비스 혼잡으로 {busy}건 실패 — 예비 모델·유료 등급 검토 필요"})
    if week_metrics["feedback"] >= 3 and (week_metrics["positive_feedback_rate"] or 0) < 0.5:
        alerts.append({"code": "negative_feedback", "message":
                       f"최근 7일 피드백 {week_metrics['feedback']}건 중 긍정 {week_metrics['positive_feedback_rate']:.0%}"})
    min_conf = _threshold("ALERT_MIN_CONFIDENCE", 0.6)
    if week_metrics["avg_confidence"] is not None and week_metrics["succeeded"] >= 3 \
            and week_metrics["avg_confidence"] < min_conf:
        alerts.append({"code": "low_confidence", "message":
                       f"최근 7일 평균 AI 신뢰도 {week_metrics['avg_confidence']:.2f} (기준 {min_conf:.2f})"})
    return alerts


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def weekly_report_text(m: dict, today: date) -> str:
    start = today - timedelta(days=7)
    lines = [
        f"📈 *주간 품질 리포트* · {start.month}/{start.day} ~ {(today - timedelta(days=1)).month}/{(today - timedelta(days=1)).day}",
        "",
        f"• 업로드 {m['uploads']}건 · 처리 성공률 {_pct(m['success_rate'])} · 처리 시간(중앙값) {m['median_processing_minutes'] or '-'}분",
        f"• 승인 {m['approved']} · 거절 {m['rejected']} · 검토 대기 {m['pending_review']} · 승인 전 수정 {_pct(m['edited_before_decision_rate'])}",
        f"• 할 일 완료율 {_pct(m['task_completion_rate'])} · 기한 지남 {m['tasks_overdue']}건",
        f"• 평균 AI 신뢰도 {m['avg_confidence'] if m['avg_confidence'] is not None else '-'} · 품질 경고 {m['low_quality']}건",
        f"• 피드백 {m['feedback']}건 · 긍정 {_pct(m['positive_feedback_rate'])}",
    ]
    if m["failures"]:
        lines.append("• 실패 유형: " + ", ".join(f"{f['label']} {f['count']}" for f in m["failures"]))
    if m["feedback_categories"]:
        lines.append("• 지적된 문제: " + ", ".join(f"{c['label']} {c['count']}" for c in m["feedback_categories"]))
    return "\n".join(lines)


def alert_channel() -> str:
    return os.getenv("MONITOR_ALERT_CHANNEL", "")


async def metrics_for(workspace, audit, days: int, today: date) -> dict:
    jobs, feedback = await asyncio.to_thread(workspace.metrics_rows, since_utc(days))
    events = await asyncio.to_thread(audit.recent, 1000)
    return compute_metrics(jobs, feedback, events, today)


async def post_admin(text: str, kind: str, storage) -> None:
    await enqueue(WriteTask(job_id=f"quality-{kind}", meeting_id="briefings", artifact="slack",
                            payload={"text": text, "suggested_channel": alert_channel()}, base_dir=storage.base_dir))


async def run_quality_checks(workspace, audit, storage, today: date, weekly: bool) -> list[dict]:
    """Called by the briefing scheduler: alert each anomaly once per day; weekly report on Mondays."""
    if not alert_channel():
        return []
    day = await metrics_for(workspace, audit, 1, today)
    week = await metrics_for(workspace, audit, 7, today)
    alerts = detect_anomalies(day, week)
    for alert in alerts:
        if await asyncio.to_thread(workspace.claim_briefing, f"alert:{alert['code']}", today.isoformat()):
            await post_admin(f"🚨 *[품질 경고]* {alert['message']}", alert["code"], storage)
    if weekly and await asyncio.to_thread(workspace.claim_briefing, "quality", today.isoformat()):
        await post_admin(weekly_report_text(week, today), "weekly", storage)
    return alerts
