# mcp_servers/mcp_stub_hardening.py

"""ASGI hardening for MCP stubs and the gateway: body cap + per-client rate limit (020).

The stubs already bind to loopback in compose and require auth, so this is defence in
depth, not the primary perimeter. The threat it closes is *inside* the perimeter: an
authenticated-but-buggy caller (or a compromised peer container) must not be able to
exhaust a stub process with one oversized payload or a request flood.

Both limits are env-configured, never magic numbers in code (050):

  MCP_MAX_BODY_BYTES              default 1 MiB
  MCP_RATE_LIMIT                  default 120 requests
  MCP_RATE_LIMIT_WINDOW_SECONDS   default 60

``GET /health`` is exempt from rate limiting: compose/k8s probes poll it on a fixed
interval, and throttling a probe restarts a perfectly healthy container.
"""

from __future__ import annotations

import contextlib
import os
import time

from collections import defaultdict, deque
from threading import Lock
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

_DEFAULT_MAX_BODY_BYTES = 1_048_576  # 1 MiB
_DEFAULT_RATE_LIMIT = 120
_DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
_HEALTH_PATH = "/health"
_RETRY_AFTER_HEADER = "Retry-After"


class _BodyTooLargeError(Exception):
    """Internal signal: the configured request-body cap was exceeded mid-stream."""


def _int_env(name: str, default: int, *, minimum: int = 1) -> int:
    """Read a positive int from the environment; fall back on blank/invalid values."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def _declared_content_length(scope: Scope) -> int | None:
    """``Content-Length`` from raw ASGI headers, or None when absent/unparsable."""
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _send_json_error(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    status_code: int,
    detail: str,
    headers: dict[str, str] | None = None,
) -> None:
    response = JSONResponse({"detail": detail}, status_code=status_code, headers=headers)
    await response(scope, receive, send)


class BodySizeLimitMiddleware:
    """Reject request bodies above ``MCP_MAX_BODY_BYTES``.

    Checks the declared ``Content-Length`` first (covers every normal MCP client),
    then caps the streamed byte count — so a chunked request cannot sidestep the
    limit by omitting the header.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        declared = _declared_content_length(scope)
        if declared is not None and declared > self._max_bytes:
            await _send_json_error(scope, receive, send, status_code=413, detail="Request body too large")
            return

        received = 0
        exceeded = False

        async def guarded_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_bytes:
                    exceeded = True
                    raise _BodyTooLargeError
            return message

        async def guarded_send(message: Message) -> None:
            # Once the cap is breached, drop whatever the app emits. An inner error
            # handler (e.g. Starlette's ServerErrorMiddleware) would otherwise turn the
            # signal into a 500 and win the race against our 413.
            if not exceeded:
                await send(message)

        # The app may swallow the signal (or wrap it in a 500); in every case the
        # response it emitted has been dropped, so the 413 below is authoritative.
        with contextlib.suppress(_BodyTooLargeError):
            await self._app(scope, guarded_receive, guarded_send)
        if exceeded:
            await _send_json_error(scope, receive, send, status_code=413, detail="Request body too large")


class RateLimitMiddleware:
    """Per-client sliding-window request budget for MCP JSON-RPC calls."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limit: int,
        window_seconds: int,
        exempt_paths: tuple[str, ...] = (_HEALTH_PATH,),
    ) -> None:
        self._app = app
        self._limit = limit
        self._window_seconds = window_seconds
        self._exempt_paths = frozenset(exempt_paths)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self._exempt_paths:
            await self._app(scope, receive, send)
            return

        retry_after = self._register_hit(_client_key(scope))
        if retry_after is not None:
            await _send_json_error(
                scope,
                receive,
                send,
                status_code=429,
                detail="Rate limit exceeded",
                headers={_RETRY_AFTER_HEADER: str(retry_after)},
            )
            return

        await self._app(scope, receive, send)

    def _register_hit(self, key: str) -> int | None:
        """Record one hit; return ``Retry-After`` seconds when the budget is spent."""
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            cutoff = now - self._window_seconds
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._limit:
                return max(1, int(self._window_seconds - (now - bucket[0])))
            bucket.append(now)
            return None


def _client_key(scope: Scope) -> str:
    client = scope.get("client")
    host = client[0] if client else "unknown"
    return f"ip:{host}"


def harden_asgi_app(app: ASGIApp) -> ASGIApp:
    """Wrap an MCP ASGI app with body-size and rate-limit middleware (020).

    Rate limiting is the outer layer so a flood is rejected before its body is read.
    """
    max_bytes = _int_env("MCP_MAX_BODY_BYTES", _DEFAULT_MAX_BODY_BYTES)
    limit = _int_env("MCP_RATE_LIMIT", _DEFAULT_RATE_LIMIT)
    window_seconds = _int_env("MCP_RATE_LIMIT_WINDOW_SECONDS", _DEFAULT_RATE_LIMIT_WINDOW_SECONDS)
    return RateLimitMiddleware(
        BodySizeLimitMiddleware(app, max_bytes=max_bytes),
        limit=limit,
        window_seconds=window_seconds,
    )
