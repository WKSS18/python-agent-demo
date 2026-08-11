"""Request correlation, lightweight rate limiting, and Prometheus metrics."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import defaultdict, deque
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.logging_config import request_id_context


logger = logging.getLogger("app.requests")
REQUESTS = Counter("fieldnote_http_requests_total", "HTTP requests", ["method", "path", "status"])
LATENCY = Histogram("fieldnote_http_request_duration_seconds", "HTTP request latency", ["method", "path"])
_BUCKETS: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_LOCK = threading.Lock()
_RULES = {
    "/auth/login": (10, 60),
    "/auth/register": (5, 300),
    "/agent/chat": (30, 60),
    "/agent/chat/stream": (30, 60),
    "/agent/files/analyze": (10, 60),
    "/uploads": (20, 60),
    "/notes/import": (10, 60),
    "/knowledge/reindex": (2, 3600),
}


class RequestMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, rate_limit_enabled: bool = True) -> None:
        super().__init__(app)
        self.rate_limit_enabled = rate_limit_enabled

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        request.state.request_id = request_id
        context_token = request_id_context.set(request_id)
        started = time.perf_counter()
        response: Response | None = None
        status_code = 500
        try:
            if self.rate_limit_enabled and request.url.path in _RULES:
                retry_after = _check_rate_limit(request)
                if retry_after is not None:
                    response = JSONResponse(
                        status_code=429,
                        content={"data": None, "code": 429, "message": "请求过于频繁，请稍后重试。"},
                        headers={"Retry-After": str(retry_after), "X-Request-ID": request_id},
                    )
                    return response
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            if response is not None:
                status_code = response.status_code
            duration = time.perf_counter() - started
            route = request.scope.get("route")
            path_label = getattr(route, "path", request.url.path)
            REQUESTS.labels(request.method, path_label, str(status_code)).inc()
            LATENCY.labels(request.method, path_label).observe(duration)
            logger.info(
                "http_request_completed",
                extra={
                    "event": "http_request_completed", "method": request.method,
                    "path": request.url.path, "status": status_code,
                    "duration_ms": round(duration * 1000, 1),
                },
            )
            request_id_context.reset(context_token)


def _check_rate_limit(request: Request) -> int | None:
    limit, window = _RULES[request.url.path]
    authorization = request.headers.get("Authorization", "")
    identity_source = authorization or (request.client.host if request.client else "unknown")
    identity = hashlib.sha256(identity_source.encode()).hexdigest()[:16]
    now = time.monotonic()
    key = (request.url.path, identity)
    with _LOCK:
        bucket = _BUCKETS[key]
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            return max(1, int(window - (now - bucket[0])))
        bucket.append(now)
    return None
