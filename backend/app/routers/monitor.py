"""
Monitoring & Feedback endpoints — Issue #22, rebuilt in #84 (internal / Slack-mode callers)

POST /monitor/feedback      — feedback from a Slack button (stored like web feedback)
GET  /monitor/metrics       — quality metrics for the last `days` (1–30)
POST /monitor/check         — run anomaly checks now (alerts go to MONITOR_ALERT_CHANNEL)
POST /monitor/weekly-report — send the weekly quality report now

The scheduled checks run inside the backend (services/briefing.py → services/quality.py).
"""
import asyncio
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.services import quality
from app.services.due_dates import team_timezone

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/monitor")


class FeedbackRequest(BaseModel):
    job_id: str
    user_id: str
    rating: Literal["good", "bad"]
    comment: str = Field("", max_length=1000)


@router.post("/feedback")
async def receive_feedback(req: FeedbackRequest, request: Request):
    ok = await asyncio.to_thread(request.app.state.workspace.save_feedback, req.job_id, f"slack:{req.user_id}",
                                 req.rating, [], req.comment.strip())
    if not ok:
        raise HTTPException(409, "분석이 끝난 회의에만 피드백을 남길 수 있습니다.")
    return {"saved": True, "job_id": req.job_id, "rating": req.rating}


@router.get("/metrics")
async def get_metrics(request: Request, days: int = Query(default=7, ge=1, le=30)):
    today = datetime.now(team_timezone()).date()
    return await quality.metrics_for(request.app.state.workspace, request.app.state.audit, days, today)


@router.post("/check")
async def run_anomaly_check(request: Request):
    state = request.app.state
    alerts = await quality.run_quality_checks(state.workspace, state.audit, state.storage,
                                              datetime.now(team_timezone()).date(), weekly=False)
    return {"alerts": alerts, "alert_channel": bool(quality.alert_channel())}


@router.post("/weekly-report")
async def trigger_weekly_report(request: Request):
    if not quality.alert_channel():
        raise HTTPException(409, "MONITOR_ALERT_CHANNEL이 설정되지 않았습니다.")
    state = request.app.state
    today = datetime.now(team_timezone()).date()
    metrics = await quality.metrics_for(state.workspace, state.audit, 7, today)
    await quality.post_admin(quality.weekly_report_text(metrics, today), "weekly-manual", state.storage)
    return {"queued": True}
