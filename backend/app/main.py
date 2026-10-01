import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.services.workspace import Workspace
from app.services.accounts import Accounts
from app.services.audit import AuditLog
from app.routers.auth import router as auth_router
from app.routers.workspace import router as workspace_router
from app.config import validate_env
from app.middleware.auth import ApiKeyMiddleware
from app.middleware.rate_limit import UploadRateLimitMiddleware
from app.routers.digest import router as digest_router
from app.routers.followup import router as followup_router
from app.routers.monitor import router as monitor_router
from app.routers.review import router as review_router
from app.routers.upload import router as upload_router
from app.storage.local import LocalStorage
from app.services.write_queue import start_worker
from app.services import llm
from app.services.retention import run_purge_loop
from app.services.briefing import run_briefing_loop

load_dotenv()
# Without this, app INFO logs (publish success, retries, pipeline progress) never reach the console.
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                    format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # per-request lines are noise
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_env()
    storage_dir = os.getenv("STORAGE_DIR", "./data/recordings")
    app.state.storage = LocalStorage(storage_dir)
    app.state.workspace = await asyncio.to_thread(Workspace, storage_dir)
    app.state.accounts = await asyncio.to_thread(
        Accounts, storage_dir, int(os.getenv("SESSION_TTL_HOURS", "12"))
    )
    await asyncio.to_thread(bootstrap_admin, app.state.accounts)
    app.state.audit = await asyncio.to_thread(AuditLog, storage_dir)
    await asyncio.to_thread(app.state.workspace.recover)
    # Start write queue worker as background task
    worker_task = asyncio.create_task(start_worker())
    purge_task = asyncio.create_task(run_purge_loop(app.state.workspace, app.state.storage, app.state.audit))
    briefing_task = asyncio.create_task(run_briefing_loop(app.state.workspace, app.state.audit, app.state.storage))
    yield
    worker_task.cancel()
    purge_task.cancel()
    briefing_task.cancel()


def bootstrap_admin(accounts: Accounts) -> None:
    """Create the first admin from env. WORKSPACE_PASSWORD (shared-password era) maps to user 'workspace'."""
    username = os.getenv("ADMIN_USERNAME") or ("workspace" if os.getenv("WORKSPACE_PASSWORD") else "admin")
    password = os.getenv("ADMIN_PASSWORD") or os.getenv("WORKSPACE_PASSWORD", "")
    if accounts.count():
        return
    if password:
        accounts.ensure_admin(username, password)
        logger.info("[Auth] Created initial admin '%s'", username)
    elif os.getenv("WORKSPACE_MODE") == "standalone":
        raise RuntimeError("ADMIN_PASSWORD가 필요합니다 — 사용자가 없어 아무도 로그인할 수 없습니다.")


app = FastAPI(title="Meeting Automation Backend", lifespan=lifespan)

app.add_middleware(ApiKeyMiddleware)
app.add_middleware(UploadRateLimitMiddleware)

origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3001").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["POST", "GET", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

app.include_router(auth_router)
app.include_router(upload_router)
app.include_router(workspace_router)
app.include_router(review_router)
app.include_router(digest_router)
app.include_router(followup_router)
app.include_router(monitor_router)


@app.get("/health")
async def health() -> dict:
    storage_dir = os.getenv("STORAGE_DIR", "./data/recordings")
    storage_ok = os.path.isdir(storage_dir)

    llm_key = llm.api_key_env()
    env_status = {
        llm_key: bool(os.getenv(llm_key)),
        "SLACK_BOT_TOKEN": bool(os.getenv("SLACK_BOT_TOKEN")),
        "OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY")),
    }

    healthy = storage_ok and env_status[llm_key] and (os.getenv("WORKSPACE_MODE") == "standalone" or env_status["SLACK_BOT_TOKEN"])

    return {
        "status": "ok" if healthy else "degraded",
        "storage": {"path": storage_dir, "accessible": storage_ok},
        "env": env_status,
        "stt_backend": os.getenv("STT_BACKEND", "whisper-api"),
        "llm_provider": llm.provider(),
    }
