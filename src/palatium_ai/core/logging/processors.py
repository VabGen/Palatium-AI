# src/palatium_ai/core/logging/processors.py

"""Structlog processors."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging

    from structlog.types import EventDict

from palatium_ai.core.observability.redaction import redact

from .context import session_id_var, trace_id_var, turn_id_var, user_id_var


def add_context_vars(logger: logging.Logger, method_name: str, event_dict: EventDict) -> EventDict:
    """Add trace_id and optional user/session/turn from context vars."""
    trace_id = trace_id_var.get()
    if trace_id:
        event_dict["trace_id"] = trace_id
    uid = user_id_var.get()
    if uid:
        event_dict["user_id"] = uid
    sid = session_id_var.get()
    if sid:
        event_dict["session_id"] = sid
    turn_id = turn_id_var.get()
    if turn_id:
        event_dict.setdefault("turn_id", turn_id)
    return event_dict


def add_timestamp(logger: logging.Logger, method_name: str, event_dict: EventDict) -> EventDict:
    """Add ISO timestamp."""
    event_dict["timestamp"] = datetime.now(UTC).isoformat()
    return event_dict


def redact_observability_strings(
    _logger: logging.Logger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """PII/token redact on every string value after enrichment, before renderer."""
    return {k: redact(v) if isinstance(v, str) else v for k, v in event_dict.items()}
