# src/palatium_ai/core/logging/processors.py

"""Модуль processors содержит функции для обогащения логов."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging

    from structlog.types import EventDict

from .context import request_id_var, session_id_var, user_id_var


def add_context_vars(logger: logging.Logger, method_name: str, event_dict: EventDict) -> EventDict:
    """Добавляет значения из контекстных переменных."""
    rid = request_id_var.get()
    if rid:
        event_dict["request_id"] = rid
    uid = user_id_var.get()
    if uid:
        event_dict["user_id"] = uid
    sid = session_id_var.get()
    if sid:
        event_dict["session_id"] = sid
    return event_dict


def add_timestamp(logger: logging.Logger, method_name: str, event_dict: EventDict) -> EventDict:
    """Добавляет временную метку в ISO формате."""
    event_dict["timestamp"] = datetime.now(UTC).isoformat()
    return event_dict
