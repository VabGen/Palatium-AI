# src/palatium_ai/core/logging/processors.py

"""Модуль processors содержит функции для обогащения логов."""

from __future__ import annotations

import inspect
import os
import socket
import time

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging

    from structlog.types import EventDict

from palatium_ai.core.config import settings

from .context import request_id_var, session_id_var, user_id_var


def add_caller_info(logger: logging.Logger, method_name: str, event_dict: EventDict) -> EventDict:
    """Добавляет имя файла, функцию и номер строки."""
    frame = inspect.currentframe()
    if frame:
        while frame:
            if frame.f_code.co_filename.find("structlog") == -1:
                break
            frame = frame.f_back
        if frame:
            event_dict["caller"] = {
                "file": frame.f_code.co_filename,
                "function": frame.f_code.co_name,
                "line": frame.f_lineno,
            }
    return event_dict


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


def add_system_info(logger: logging.Logger, method_name: str, event_dict: EventDict) -> EventDict:
    """Добавляет системную информацию: хост, процесс, версию, окружение."""
    event_dict.setdefault("host", socket.gethostname())
    event_dict.setdefault("pid", os.getpid())
    event_dict.setdefault("app_version", settings.APP_VERSION)
    event_dict.setdefault("environment", settings.ENVIRONMENT)
    return event_dict


def add_timestamp(logger: logging.Logger, method_name: str, event_dict: EventDict) -> EventDict:
    """Добавляет временную метку в ISO формате с миллисекундами."""
    event_dict["timestamp"] = time.strftime(
        f"%Y-%m-%dT%H:%M:%S.{int(time.time() * 1000) % 1000:03d}Z",
        time.gmtime(time.time()),
    )
    return event_dict
