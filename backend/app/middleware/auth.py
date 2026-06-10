"""
API Key authentication middleware.

Checks X-API-Key header against BACKEND_API_KEY env var.
Exempt paths: /health (liveness probe), /docs, /openapi.json (FastAPI dev UI).

If BACKEND_API_KEY is not set, middleware is a no-op (local dev convenience).
"""
import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

_EXEMPT = {"/health", "/docs", "/openapi.json", "/redoc"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        api_key = os.getenv("BACKEND_API_KEY", "")
        if not api_key:
            return await call_next(request)

        if request.url.path in _EXEMPT:
            return await call_next(request)

        provided = request.headers.get("X-API-Key", "")
        if provided != api_key:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        return await call_next(request)
