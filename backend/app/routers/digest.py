"""
Digest & Brief HTTP endpoints — Issue #20, rebuilt in #83

POST /digest/morning   — Morning Brief now (approved meetings, due tasks)
POST /digest/daily     — same as morning (yesterday's approved meetings are part of it)
POST /digest/weekly    — Weekly Digest now
POST /digest/agenda    — 어젠다 후보 생성

Scheduled delivery runs inside the backend (services/briefing.py); these are for manual/cron use.
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel

from app.services.briefing import send_briefing
from app.services.digest import send_meeting_agenda

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/digest")


class AgendaRequest(BaseModel):
    summaries: list[str]
    lang: str = "ko"


def _trigger(kind: str, request: Request, background_tasks: BackgroundTasks) -> dict:
    state = request.app.state
    background_tasks.add_task(send_briefing, kind, state.workspace, state.audit, state.storage)
    return {"triggered": kind}


@router.post("/morning")
async def trigger_morning_brief(request: Request, background_tasks: BackgroundTasks):
    return _trigger("morning", request, background_tasks)


@router.post("/daily")
async def trigger_daily_digest(request: Request, background_tasks: BackgroundTasks):
    return _trigger("morning", request, background_tasks)


@router.post("/weekly")
async def trigger_weekly_digest(request: Request, background_tasks: BackgroundTasks):
    return _trigger("weekly", request, background_tasks)


@router.post("/agenda")
async def trigger_agenda(req: AgendaRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(send_meeting_agenda, req.summaries, req.lang)
    return {"triggered": "meeting_agenda", "count": len(req.summaries)}
