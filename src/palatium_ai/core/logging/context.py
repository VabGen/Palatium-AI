# src/palatium_ai/core/logging/context.py

"""Context variables for correlated structlog fields (040: trace_id)."""

from __future__ import annotations

from contextvars import ContextVar

trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
session_id_var: ContextVar[str | None] = ContextVar("session_id", default=None)

# Backward-compatible alias (deprecated — use trace_id_var).
request_id_var = trace_id_var
