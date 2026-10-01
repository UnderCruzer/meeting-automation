import asyncio
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.middleware.rate_limit import client_ip
from app.routers.auth import current_user
from app.services.accounts import User
from app.services.retention import delete_job
from app.services.workspace import JobBusyError

router = APIRouter(prefix="/workspace", dependencies=[Depends(current_user)])

class Decision(BaseModel):
    status: Literal["approved", "rejected"]

@router.get("/jobs")
async def jobs(request: Request):
    return await asyncio.to_thread(request.app.state.workspace.list)

@router.post("/jobs/{job_id}/decision")
async def decide(job_id: str, decision: Decision, request: Request, user: Optional[User] = Depends(current_user)):
    username = user.username if user else None
    changed = await asyncio.to_thread(request.app.state.workspace.decide, job_id, decision.status, username)
    if not changed:
        raise HTTPException(409, "검토 가능한 회의가 없거나 이미 처리되었습니다.")
    title = await asyncio.to_thread(request.app.state.workspace.title, job_id)
    await _audit(request, "approve" if decision.status == "approved" else "reject", username, job_id=job_id, title=title)
    return {"status": decision.status}


@router.delete("/jobs/{job_id}")
async def delete_meeting(job_id: str, request: Request, user: Optional[User] = Depends(current_user)):
    title = await asyncio.to_thread(request.app.state.workspace.title, job_id)
    try:
        deleted = await delete_job(request.app.state.workspace, request.app.state.storage, job_id)
    except JobBusyError:
        raise HTTPException(409, "분석 중인 회의는 삭제할 수 없습니다. 완료 후 다시 시도해주세요.")
    except ValueError:
        raise HTTPException(404, "회의를 찾을 수 없습니다.")
    if not deleted:
        raise HTTPException(404, "회의를 찾을 수 없습니다.")
    await _audit(request, "delete", user.username if user else None, job_id=job_id, title=title)
    return {"deleted": job_id}


async def _audit(request: Request, action: str, username: Optional[str], **fields) -> None:
    audit = getattr(request.app.state, "audit", None)
    if audit is not None:
        await asyncio.to_thread(audit.record, action, username, ip=client_ip(request), **fields)
