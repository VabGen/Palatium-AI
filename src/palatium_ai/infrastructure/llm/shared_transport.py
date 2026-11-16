# src/palatium_ai/infrastructure/llm/shared_transport.py

"""One shared HTTP transport for every LLM call in the process (080).

LiteLLM's default transport builds a new ``aiohttp.ClientSession`` per request when
the caller passes no ``shared_session``. Those sessions are only finalized by the
garbage collector, which (a) logs ``Unclosed client session`` and (b) keeps sockets
and buffers alive until the GC runs — a slow leak in a long-lived API worker.

The contract here is the opposite: one session per event loop, created on first use
and closed by the composition root on shutdown. Uvicorn workers each own one loop, so
"per loop" is "per worker" in production, while the test suite (a fresh loop per test)
never reuses a session bound to a loop that is already closed.
"""

from __future__ import annotations

import asyncio

from weakref import WeakKeyDictionary

from aiohttp import ClientSession, DummyCookieJar, TCPConnector

from palatium_ai.core.logging import get_logger

logger = get_logger(__name__)

# Bounded pool: the LLM gateway is a single upstream, so a large global limit would only
# hide a runaway fan-out. Per-host equals the global limit for the same reason (080).
_CONNECTION_LIMIT = 64


_sessions: WeakKeyDictionary[asyncio.AbstractEventLoop, ClientSession] = WeakKeyDictionary()


def shared_client_session() -> ClientSession:
    """Return this loop's session, creating it on first use.

    Must be called from a running loop: an ``aiohttp`` session binds its connector to
    the loop it was created in, so a session from another loop would raise at request
    time instead of at creation.
    """
    loop = asyncio.get_running_loop()
    session = _sessions.get(loop)
    if session is not None and not session.closed:
        return session
    session = ClientSession(
        connector=TCPConnector(limit=_CONNECTION_LIMIT, limit_per_host=_CONNECTION_LIMIT),
        # LLM gateways do not need cookies; skipping the jar avoids shared state.
        cookie_jar=DummyCookieJar(),
    )
    _sessions[loop] = session
    logger.info("llm.transport.session_created", connection_limit=_CONNECTION_LIMIT)
    return session


async def aclose_shared_client_sessions() -> None:
    """Close every session this process created (idempotent; safe at shutdown)."""
    sessions = list(_sessions.values())
    _sessions.clear()
    for session in sessions:
        if session.closed:
            continue
        try:
            await session.close()
        except Exception:  # noqa: BLE001  # shutdown must not fail on a dead transport (035)
            logger.warning("llm.transport.session_close_failed", error="close failed")
    if sessions:
        logger.info("llm.transport.sessions_closed", count=len(sessions))


__all__ = ["aclose_shared_client_sessions", "shared_client_session"]
