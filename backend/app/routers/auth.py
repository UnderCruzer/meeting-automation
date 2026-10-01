"""Login, sessions and user management. Called only by the web server (API key required)."""
from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.middleware.rate_limit import client_ip
from app.services.accounts import AccountError, User

router = APIRouter(prefix="/auth")

# Per-username lockout (the web server also limits per IP).
_MAX_FAILURES = 5
_WINDOW = 15 * 60
_failures: dict[str, tuple[int, float]] = {}
_failures_lock = threading.Lock()


def _locked(username: str) -> bool:
    with _failures_lock:
        count, reset_at = _failures.get(username, (0, 0.0))
        return count >= _MAX_FAILURES and reset_at > time.monotonic()


def _record_failure(username: str) -> None:
    now = time.monotonic()
    with _failures_lock:
        count, reset_at = _failures.get(username, (0, 0.0))
        _failures[username] = (count + 1, reset_at) if reset_at > now else (1, now + _WINDOW)


async def _audit(request: Request, action: str, username: Optional[str], detail: Optional[str] = None) -> None:
    audit = getattr(request.app.state, "audit", None)
    if audit is not None:
        await asyncio.to_thread(audit.record, action, username, detail=detail, ip=client_ip(request))


def auth_required() -> bool:
    return (os.getenv("WORKSPACE_MODE") == "standalone"
            or bool(os.getenv("ADMIN_PASSWORD") or os.getenv("WORKSPACE_PASSWORD")))


def session_token(request: Request) -> str:
    return request.headers.get("X-Session-Token", "")


async def current_user(request: Request) -> Optional[User]:
    """Signed-in user, or None when accounts are not enabled (legacy Slack mode)."""
    user = await asyncio.to_thread(request.app.state.accounts.session_user, session_token(request))
    if user is None and auth_required():
        raise HTTPException(401, "로그인이 필요합니다.")
    return user


async def require_admin(request: Request) -> User:
    user = await current_user(request)
    if user is None or not user.is_admin:
        raise HTTPException(403, "관리자만 사용할 수 있습니다.")
    return user


class LoginBody(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    current: str
    new: str


class NewUserBody(BaseModel):
    username: str
    password: str
    role: Literal["admin", "member"] = "member"


class UpdateUserBody(BaseModel):
    active: Optional[bool] = None
    role: Optional[Literal["admin", "member"]] = None
    password: Optional[str] = None


@router.post("/login")
async def login(body: LoginBody, request: Request):
    name = body.username.strip().lower()
    if _locked(name):
        raise HTTPException(429, "로그인 시도가 너무 많습니다. 15분 후 다시 시도해주세요.")
    accounts = request.app.state.accounts
    user = await asyncio.to_thread(accounts.authenticate, name, body.password)
    if user is None:
        _record_failure(name)
        await _audit(request, "login_failed", name[:32])
        raise HTTPException(401, "사용자 이름 또는 비밀번호가 맞지 않습니다.")
    token = await asyncio.to_thread(accounts.start_session, user)
    await _audit(request, "login", user.username)
    return {"token": token, "user": user.public(), "maxAge": accounts.session_hours * 3600}


@router.post("/logout")
async def logout(request: Request):
    accounts = request.app.state.accounts
    user = await asyncio.to_thread(accounts.session_user, session_token(request))
    await asyncio.to_thread(accounts.end_session, session_token(request))
    if user:
        await _audit(request, "logout", user.username)
    return {"ok": True}


@router.get("/me")
async def me(user: Optional[User] = Depends(current_user)):
    return {"user": user.public() if user else None}


@router.post("/password")
async def change_password(body: PasswordBody, request: Request, user: Optional[User] = Depends(current_user)):
    if user is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    try:
        await asyncio.to_thread(request.app.state.accounts.change_password, user, body.current, body.new,
                                session_token(request))
    except AccountError as exc:
        raise HTTPException(400, str(exc))
    await _audit(request, "password_change", user.username)
    return {"ok": True}


@router.get("/users")
async def list_users(request: Request, _: User = Depends(require_admin)):
    users = await asyncio.to_thread(request.app.state.accounts.list)
    return [u.public() for u in users]


@router.post("/users")
async def create_user(body: NewUserBody, request: Request, actor: User = Depends(require_admin)):
    try:
        user = await asyncio.to_thread(request.app.state.accounts.create, body.username, body.password, body.role)
    except AccountError as exc:
        raise HTTPException(400, str(exc))
    await _audit(request, "user_create", actor.username, f"{user.username} ({user.role})")
    return user.public()


@router.patch("/users/{user_id}")
async def update_user(user_id: int, body: UpdateUserBody, request: Request, actor: User = Depends(require_admin)):
    try:
        user = await asyncio.to_thread(
            lambda: request.app.state.accounts.update(
                actor, user_id, active=body.active, role=body.role, password=body.password)
        )
    except AccountError as exc:
        raise HTTPException(400, str(exc))
    changes = [f"active={body.active}" if body.active is not None else "",
               f"role={body.role}" if body.role else "", "password reset" if body.password else ""]
    await _audit(request, "user_update", actor.username, f"{user.username}: " + ", ".join(c for c in changes if c))
    return user.public()


@router.get("/audit")
async def audit_log(request: Request, limit: int = 200, _: User = Depends(require_admin)):
    return await asyncio.to_thread(request.app.state.audit.recent, limit)
