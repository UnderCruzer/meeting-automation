"""
Digest & Brief HTTP endpoints — Issue #20

POST /digest/morning   — Morning Brief 즉시 트리거 (cron 또는 수동)
POST /digest/daily     — Daily Digest 즉시 트리거
POST /digest/weekly    — Weekly Digest 즉시 트리거
POST /digest/agenda    — 어젠다 후보 생성
"""
import logging

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from app.services.digest import (
    send_daily_digest,
    send_meeting_agenda,
    send_morning_brief,
    send_weekly_digest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/digest")


class AgendaRequest(BaseModel):
    summaries: list[str]
    lang: str = "ko"


@router.post("/morning")
async def trigger_morning_brief(background_tasks: BackgroundTasks, lang: str = "ko"):
    background_tasks.add_task(send_morning_brief, lang)
    return {"triggered": "morning_brief", "lang": lang}


@router.post("/daily")
async def trigger_daily_digest(background_tasks: BackgroundTasks, lang: str = "ko"):
    background_tasks.add_task(send_daily_digest, lang)
    return {"triggered": "daily_digest", "lang": lang}


@router.post("/weekly")
async def trigger_weekly_digest(background_tasks: BackgroundTasks, lang: str = "ko"):
    background_tasks.add_task(send_weekly_digest, lang)
    return {"triggered": "weekly_digest", "lang": lang}


@router.post("/agenda")
async def trigger_agenda(req: AgendaRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(send_meeting_agenda, req.summaries, req.lang)
    return {"triggered": "meeting_agenda", "count": len(req.summaries)}
