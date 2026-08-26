# src/palatium_ai/core/logging/decorators.py

"""Модуль decorators содержит декораторы для логирования времени выполнения sync/async функций."""

from __future__ import annotations

import time

from functools import wraps
from typing import TYPE_CHECKING, ParamSpec, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import structlog

from .logger import get_logger

P = ParamSpec("P")
R = TypeVar("R")


def log_execution_time(
    logger: structlog.stdlib.BoundLogger | None = None,
) -> Callable[[Callable[P, Awaitable[R] | R]], Callable[P, Awaitable[R] | R]]:
    """Декоратор для логирования времени выполнения sync/async функций."""

    def decorator(func: Callable[P, Awaitable[R] | R]) -> Callable[P, Awaitable[R] | R]:
        log = logger or get_logger(func.__module__)

        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time.perf_counter()
            try:
                result = await cast("Awaitable[R]", func(*args, **kwargs))
                duration = time.perf_counter() - start
                log.info("Async function executed", function=func.__name__, duration_ms=duration * 1000, success=True)
                return result
            except Exception as e:
                duration = time.perf_counter() - start
                log.error(
                    "Async function failed",
                    function=func.__name__,
                    duration_ms=duration * 1000,
                    error=str(e),
                    exc_info=True,
                )
                raise

        @wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time.perf_counter()
            try:
                result = cast("R", func(*args, **kwargs))
                duration = time.perf_counter() - start
                log.info("Function executed", function=func.__name__, duration_ms=duration * 1000, success=True)
                return result
            except Exception as e:
                duration = time.perf_counter() - start
                log.error(
                    "Function failed", function=func.__name__, duration_ms=duration * 1000, error=str(e), exc_info=True
                )
                raise

        import inspect

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
