# src/palatium_ai/core/logging/decorators.py

"""Модуль decorators содержит декораторы для логирования."""

from __future__ import annotations

import time

from functools import wraps
from typing import TYPE_CHECKING, ParamSpec, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

    import structlog

from .logger import get_logger

P = ParamSpec("P")
R = TypeVar("R")


def log_execution_time(
    logger: structlog.stdlib.BoundLogger | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Декоратор для логирования времени выполнения функции."""

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
