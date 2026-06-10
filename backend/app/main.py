import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_env()
    storage_dir = os.getenv("STORAGE_DIR", "./data/recordings")
    app.state.storage = LocalStorage(storage_dir)
    # Start write queue worker as background task
    worker_task = asyncio.create_task(start_worker())
    yield
    worker_task.cancel()


app = FastAPI(title="Meeting Automation Backend", lifespan=lifespan)

app.add_middleware(ApiKeyMiddleware)
app.add_middleware(UploadRateLimitMiddleware)

origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3001").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

app.include_router(upload_router)
app.include_router(review_router)
app.include_router(digest_router)
app.include_router(followup_router)
app.include_router(monitor_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
