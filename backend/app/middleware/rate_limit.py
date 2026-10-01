"""
Sliding-window rate limiter middleware for POST /upload.

Limit: UPLOAD_RATE_LIMIT requests per UPLOAD_RATE_WINDOW seconds per client IP.
Defaults: 10 requests / 60 seconds.

Behind the web proxy every request comes from 127.0.0.1, so X-Client-IP is used
instead — but only when the request carries the valid backend API key (this
middleware runs before ApiKeyMiddleware, so it checks the key itself).

In-memory store — resets on restart. Sufficient for single-instance MVP.
Replace with Redis + lua script for multi-instance deployments.
"""
import hmac
import os
import time
import threading
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class UploadRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit: int = 0, window: int = 0):
        super().__init__(app)
        # 0 means "read from env at startup" — allows override in tests
        self._limit = limit or int(os.getenv("UPLOAD_RATE_LIMIT", "10"))
        self._window = window or int(os.getenv("UPLOAD_RATE_WINDOW", "60"))
        self._lock = threading.Lock()
        self._windows: dict[str, deque] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        if request.method != "POST" or request.url.path != "/upload":
            return await call_next(request)

        limit, window = self._limit, self._window
        ip = client_ip(request)
        now = time.monotonic()

        with self._lock:
            q = self._windows[ip]
            # Purge timestamps outside the sliding window
            while q and now - q[0] > window:
                q.popleft()

            if len(q) >= limit:
                retry_after = int(window - (now - q[0])) + 1
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"업로드 요청이 너무 많습니다. {retry_after}초 후 재시도해주세요."},
                    headers={"Retry-After": str(retry_after)},
                )
            q.append(now)

        return await call_next(request)


def client_ip(request: Request) -> str:
    """Real client IP: X-Client-IP from the authenticated web proxy, else the socket peer."""
    api_key = os.getenv("BACKEND_API_KEY", "")
    forwarded = request.headers.get("X-Client-IP", "").strip()
    provided = request.headers.get("X-API-Key", "")
    if api_key and forwarded and hmac.compare_digest(provided.encode(), api_key.encode()):
        return forwarded
    return request.client.host if request.client else "unknown"
