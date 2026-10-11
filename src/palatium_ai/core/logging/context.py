# src/palatium_ai/core/logging/context.py

"""Context variables for correlated structlog fields (040).

Three correlation scopes, never conflated:
- ``session_id`` — conversation (``thread_id``), spans many turns;
- ``turn_id`` — one user turn (graph ``task_id``; checkpoint key ``thread_id:turn_id``);
- ``trace_id`` — one HTTP/SSE request (OTel trace; a HITL resume is a new request
  for the same ``turn_id``).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
session_id_var: ContextVar[str | None] = ContextVar("session_id", default=None)
turn_id_var: ContextVar[str | None] = ContextVar("turn_id", default=None)

# Backward-compatible alias (deprecated — use trace_id_var).
request_id_var = trace_id_var


@contextmanager
def bind_turn_log_context(*, session_id: str, turn_id: str) -> Iterator[None]:
    """Stamp ``session_id`` + ``turn_id`` on every log line of one graph turn."""
    session_token = session_id_var.set(session_id)
    turn_token = turn_id_var.set(turn_id)
    try:
        yield
    finally:
        turn_id_var.reset(turn_token)
        session_id_var.reset(session_token)
