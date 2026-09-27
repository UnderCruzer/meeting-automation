import asyncio
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/workspace")

class Decision(BaseModel):
    status: Literal["approved", "rejected"]

@router.get("/jobs")
async def jobs(request: Request):
    return await asyncio.to_thread(request.app.state.workspace.list)

@router.post("/jobs/{job_id}/decision")
async def decide(job_id: str, decision: Decision, request: Request):
    changed = await asyncio.to_thread(request.app.state.workspace.decide, job_id, decision.status)
    if not changed:
        raise HTTPException(409, "검토 가능한 회의가 없거나 이미 처리되었습니다.")
    return {"status": decision.status}
