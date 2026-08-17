# src/palatium_ai/core/logging/setup.py
from __future__ import annotations

import logging
import logging.handlers
import sys

from typing import TYPE_CHECKING

import structlog

from .filters import SuppressFilter
from .processors import add_context_vars, add_timestamp

if TYPE_CHECKING:
    from structlog.types import Processor

    from palatium_ai.core.config import Settings


def setup_logging(settings: Settings) -> None:
    """Настраивает логирование на основе объекта Settings (Dependency Injection)."""
    log_cfg = settings.logging
    app_cfg = settings.app

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        app_version=app_cfg.version,
        environment=app_cfg.environment,
        app_name=app_cfg.name,
    )

    base_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        add_timestamp,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.CallsiteParameterAdder(
            parameters=[
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            ]
        ),
        add_context_vars,
    ]

    renderer: Processor
    if log_cfg.json_logs:
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
    root_logger.setLevel(getattr(logging, log_cfg.level.upper(), logging.INFO))

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    console_handler.setLevel(getattr(logging, log_cfg.level.upper(), logging.INFO))
    root_logger.addHandler(console_handler)

    if log_cfg.file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_cfg.file, maxBytes=10_485_760, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        file_handler.setLevel(getattr(logging, log_cfg.level.upper(), logging.INFO))
        root_logger.addHandler(file_handler)

    for mod in log_cfg.suppress_modules:
        logging.getLogger(mod).setLevel(logging.WARNING)

    if log_cfg.filter_modules:
        root_logger.addFilter(SuppressFilter(log_cfg.filter_modules))
