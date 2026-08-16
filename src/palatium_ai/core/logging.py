# palatium_ai/core/logging.py

"""Настройка структурированного логирования."""

from __future__ import annotations

import inspect
import logging
import logging.handlers
import os
import socket
import sys
import time

from contextvars import ContextVar
from functools import wraps
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

import structlog

from palatium_ai.core.config import settings

if TYPE_CHECKING:
    from collections.abc import Callable

    from structlog.types import EventDict, Processor

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
session_id_var: ContextVar[str | None] = ContextVar("session_id", default=None)


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
    """Добавляет значения из контекстных переменных (request_id, user_id, session_id)."""
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
    """Добавляет системную информацию: хост, процесс, версию приложения, окружение."""
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


class SuppressFilter(logging.Filter):
    """Фильтр, который не пропускает логи из указанных модулей."""

    def __init__(self, modules: list[str]) -> None:
        self.modules = modules

    def filter(self, record: logging.LogRecord) -> bool:
        """Возвращает True, если запись не из указанных модулей."""
        return not any(record.name.startswith(m) for m in self.modules)


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

    # Консольный хендлер
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    root_logger.addHandler(console_handler)

    # Файловый хендлер
    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10_485_760,  # 10 MB
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
    """Удобная функция для настройки логирования из переменных окружения."""
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


# ------------------------------------------------------------------
# Функция для получения логгера
# ------------------------------------------------------------------
def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Возвращает структурированный логгер с именем модуля."""
    if name is None:
        name = __name__
    return structlog.get_logger(name)


# ------------------------------------------------------------------
# Декоратор для логирования времени выполнения
# ------------------------------------------------------------------
P = ParamSpec("P")
R = TypeVar("R")


def log_execution_time(
    logger: structlog.stdlib.BoundLogger | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Декоратор для логирования времени выполнения функции.

    Пример:
        @log_execution_time()
        def my_func():
            ...
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            nonlocal logger
            if logger is None:
                logger = get_logger(func.__module__)
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration = time.perf_counter() - start
                logger.info(
                    "Function executed",
                    function=func.__name__,
                    duration_ms=duration * 1000,
                    success=True,
                )
                return result
            except Exception as e:
                duration = time.perf_counter() - start
                logger.error(
                    "Function failed",
                    function=func.__name__,
                    duration_ms=duration * 1000,
                    error=str(e),
                    exc_info=True,
                )
                raise

        return wrapper

    return decorator


# ------------------------------------------------------------------
# Корневой логгер для пакета (по умолчанию)
# ------------------------------------------------------------------
logger = get_logger("palatium_ai")

# setup_logging_from_settings()
