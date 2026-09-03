# src/palatium_ai/core/observability/trace_context.py

"""Resolve and mint distributed trace identifiers (040)."""

from __future__ import annotations

import re
import uuid

_TRACE_HEADER = "x-trace-id"
_TRACEPARENT_RE = re.compile(r"^[\da-f]{2}-([\da-f]{32})-[\da-f]{16}-[\da-f]{2}$", re.IGNORECASE)


def resolve_trace_id(*, header_value: str | None, traceparent: str | None = None) -> str:
    """Return client trace id or mint a new correlation id."""
    for candidate in (header_value, _trace_id_from_traceparent(traceparent)):
        if candidate:
            cleaned = candidate.strip()
            if cleaned:
                return cleaned[:128]
    return uuid.uuid4().hex


def trace_id_header_name() -> str:
    """Canonical response/request header for correlation."""
    return "X-Trace-Id"


def _trace_id_from_traceparent(value: str | None) -> str | None:
    if not value:
        return None
    match = _TRACEPARENT_RE.match(value.strip())
    if match is None:
        return None
    return match.group(1)
