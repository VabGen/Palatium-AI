# src/palatium_ai/core/logging/setup.py

"""Модуль setup содержит функции для настройки structlog и стандартного logging."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from typing import TYPE_CHECKING, Any

import structlog

from palatium_ai.core.config import settings

from .filters import SuppressFilter
from .processors import (
    add_caller_info,
    add_context_vars,
    add_system_info,
    add_timestamp,
)

if TYPE_CHECKING:
    from structlog.types import Processor


def configure_structlog(
    json_output: bool = False,
    level: str = "INFO",
    log_file: str | None = None,
    json_file: str | None = None,
    suppress_modules: str = "urllib3,asyncio,httpx",
    filter_modules: str = "",
) -> None:
    """Настройка глобальной конфигурации structlog с поддержкой файлов."""
    base_processors: list[Processor] = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        add_timestamp,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        add_system_info,
        add_caller_info,
        add_context_vars,
    ]

    renderer: Any
    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            pad_event=30,
            exception_formatter=structlog.dev.rich_traceback,
        )

    structlog.configure(
        processors=base_processors + [renderer],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    root_logger.addHandler(console_handler)

    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10_485_760,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        root_logger.addHandler(file_handler)

    if json_file and json_file != log_file:
        json_file_handler = logging.handlers.RotatingFileHandler(
            json_file,
            maxBytes=10_485_760,
            backupCount=5,
            encoding="utf-8",
        )
        json_file_handler.setFormatter(logging.Formatter("%(message)s"))
        json_file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        root_logger.addHandler(json_file_handler)

    for mod in suppress_modules.split(","):
        if mod:
            logging.getLogger(mod).setLevel(logging.WARNING)

    if filter_modules:
        modules_list = [m.strip() for m in filter_modules.split(",") if m.strip()]
        if modules_list:
            root_logger.addFilter(SuppressFilter(modules_list))


def setup_logging_from_settings() -> None:
    """Настраивает логирование на основе глобального объекта settings."""
    configure_structlog(
        json_output=settings.LOG_JSON,
        level=settings.LOG_LEVEL,
        log_file=settings.LOG_FILE,
        json_file=settings.LOG_JSON_FILE,
        suppress_modules=settings.LOG_SUPPRESS_MODULES,
        filter_modules=settings.LOG_FILTER_MODULES,
    )


def setup_logging(
    json_output: bool | None = None,
    level: str | None = None,
    log_file: str | None = None,
    json_file: str | None = None,
) -> None:
    """Функция для ручной настройки логирования (из os.environ или аргументов)."""
    import os

    if json_output is None:
        json_output = os.getenv("LOG_JSON", "false").lower() == "true"
    if level is None:
        level = os.getenv("LOG_LEVEL", "INFO")
    if log_file is None:
        log_file = os.getenv("LOG_FILE")
    if json_file is None:
        json_file = os.getenv("LOG_JSON_FILE")
    configure_structlog(
        json_output=json_output,
        level=level,
        log_file=log_file,
        json_file=json_file,
        suppress_modules=os.getenv("LOG_SUPPRESS_MODULES", "urllib3,asyncio,httpx"),
        filter_modules=os.getenv("LOG_FILTER_MODULES", ""),
    )
