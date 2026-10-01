import asyncio
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.routers.auth import current_user
from app.services.retention import delete_job
from app.services.workspace import JobBusyError

router = APIRouter(prefix="/workspace", dependencies=[Depends(current_user)])

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


@router.delete("/jobs/{job_id}")
async def delete_meeting(job_id: str, request: Request):
    try:
        deleted = await delete_job(request.app.state.workspace, request.app.state.storage, job_id)
    except JobBusyError:
        raise HTTPException(409, "분석 중인 회의는 삭제할 수 없습니다. 완료 후 다시 시도해주세요.")
    except ValueError:
        raise HTTPException(404, "회의를 찾을 수 없습니다.")
    if not deleted:
        raise HTTPException(404, "회의를 찾을 수 없습니다.")
    return {"deleted": job_id}
