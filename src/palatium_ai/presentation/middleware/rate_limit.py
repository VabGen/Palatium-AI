# src/palatium_ai/presentation/middleware/rate_limit.py

"""In-process fixed-window rate limiter for expensive API routes."""

from __future__ import annotations

import time

from collections import defaultdict, deque
from threading import Lock
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Limit requests per principal (or client IP) within a sliding window."""

    DEFAULT_PATH_PREFIXES: tuple[str, ...] = (
        "/api/intents/",
        "/api/hitl/",
        "/api/documents/",
        "/api/memory/",
        "/api/sessions/",
        "/api/admin/",
        "/api/agents/",
    )

    def __init__(
        self,
        app: ASGIApp,
        *,
        limit: int,
        window_seconds: int,
        path_prefixes: tuple[str, ...] | None = None,
    ) -> None:
        super().__init__(app)
        self._limit = limit
        self._window_seconds = window_seconds
        self._path_prefixes = path_prefixes or self.DEFAULT_PATH_PREFIXES
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Enforce per-principal request budget on configured path prefixes."""
        path = request.url.path
        if not any(path.startswith(prefix) for prefix in self._path_prefixes):
            return await call_next(request)

        key = _client_key(request)
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            cutoff = now - self._window_seconds
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._limit:
                retry_after = max(1, int(self._window_seconds - (now - bucket[0])))
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)

        return await call_next(request)


def _client_key(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    subject = getattr(principal, "subject", None)
    if isinstance(subject, str) and subject:
        return f"sub:{subject}"
    client = request.client
    host = client.host if client is not None else "unknown"
    return f"ip:{host}"
