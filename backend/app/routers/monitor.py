"""
Monitoring & Feedback endpoints — Issue #22

POST /monitor/feedback      — Slack 피드백 버튼에서 수신
GET  /monitor/metrics       — 메트릭 조회 (since_hours 파라미터)
POST /monitor/check         — 이상 탐지 즉시 실행
POST /monitor/weekly-report — 주간 리포트 즉시 발송
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Query
from pydantic import BaseModel

from app.services.monitoring import (
    check_anomalies,
    compute_metrics,
    save_feedback,
    send_weekly_report,
)
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/monitor")


class FeedbackRequest(BaseModel):
    job_id: str
    user_id: str
    rating: str          # "good" | "bad" | "partial"
    comment: str = ""


@router.post("/feedback")
async def receive_feedback(req: FeedbackRequest):
    save_feedback(req.job_id, req.user_id, req.rating, req.comment)
    return {"saved": True, "job_id": req.job_id, "rating": req.rating}


@router.get("/metrics")
async def get_metrics(since_hours: int = Query(default=24, ge=1, le=720)):
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    return compute_metrics(since)


@router.post("/check")
async def run_anomaly_check(background_tasks: BackgroundTasks, since_hours: int = Query(default=1, ge=1)):
    background_tasks.add_task(check_anomalies, since_hours)
    return {"triggered": "anomaly_check", "since_hours": since_hours}


@router.post("/weekly-report")
async def trigger_weekly_report(background_tasks: BackgroundTasks):
    background_tasks.add_task(send_weekly_report)
    return {"triggered": "weekly_report"}
