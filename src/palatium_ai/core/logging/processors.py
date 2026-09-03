# src/palatium_ai/core/logging/processors.py

"""Structlog processors."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging

    from structlog.types import EventDict

from .context import session_id_var, trace_id_var, user_id_var


def add_context_vars(logger: logging.Logger, method_name: str, event_dict: EventDict) -> EventDict:
    """Add trace_id and optional user/session from context vars."""
    trace_id = trace_id_var.get()
    if trace_id:
        event_dict["trace_id"] = trace_id
    uid = user_id_var.get()
    if uid:
        event_dict["user_id"] = uid
    sid = session_id_var.get()
    if sid:
        event_dict["session_id"] = sid
    return event_dict


def add_timestamp(logger: logging.Logger, method_name: str, event_dict: EventDict) -> EventDict:
    """Add ISO timestamp."""
    event_dict["timestamp"] = datetime.now(UTC).isoformat()
    return event_dict
