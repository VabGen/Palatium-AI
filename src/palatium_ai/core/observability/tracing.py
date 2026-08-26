# src/palatium_ai/core/observability/tracing.py

"""Обёртка трассировки (LangSmith с fallback на structlog)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar, cast

import structlog

logger = structlog.get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def _structlog_traceable(*, name: str | None = None) -> Callable[[Callable[P, R]], Callable[P, R]]:
    run_name = name or "unknown"

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            logger.debug("trace.start", run_name=run_name, func=func.__name__)
            try:
                result: R = await cast("Callable[P, Awaitable[R]]", func)(*args, **kwargs)
                logger.debug("trace.end", run_name=run_name, func=func.__name__)
                return result
            except Exception as exc:
                logger.warning("trace.error", run_name=run_name, error=str(exc))
                raise

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]

        @wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            logger.debug("trace.start", run_name=run_name, func=func.__name__)
            try:
                result = func(*args, **kwargs)
                logger.debug("trace.end", run_name=run_name, func=func.__name__)
                return result
            except Exception as exc:
                logger.warning("trace.error", run_name=run_name, error=str(exc))
                raise

        return sync_wrapper

    return decorator


try:
    from langsmith import traceable as traceable
except ImportError:  # pragma: no cover
    traceable = _structlog_traceable  # type: ignore[assignment]
