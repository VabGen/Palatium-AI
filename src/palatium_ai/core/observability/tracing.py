# src/palatium_ai/core/observability/tracing.py

"""OTel-primary tracing with structlog fallback (040)."""

from __future__ import annotations

import asyncio

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar, cast

import structlog

from palatium_ai.core.observability.otel import get_tracer

logger = structlog.get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def traceable(*, name: str | None = None) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator: OTel span when tracer is configured, else structlog trace events."""
    span_name = name or "unknown"

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            tracer = get_tracer()
            if tracer is not None:
                with tracer.start_as_current_span(span_name):
                    return await cast("Callable[P, Awaitable[R]]", func)(*args, **kwargs)
            logger.debug("trace.start", run_name=span_name, func=func.__name__)
            try:
                result: R = await cast("Callable[P, Awaitable[R]]", func)(*args, **kwargs)
                logger.debug("trace.end", run_name=span_name, func=func.__name__)
                return result
            except Exception as exc:
                logger.warning("trace.error", run_name=span_name, error=str(exc))
                raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]

        @wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            tracer = get_tracer()
            if tracer is not None:
                with tracer.start_as_current_span(span_name):
                    return func(*args, **kwargs)
            logger.debug("trace.start", run_name=span_name, func=func.__name__)
            try:
                result = func(*args, **kwargs)
                logger.debug("trace.end", run_name=span_name, func=func.__name__)
                return result
            except Exception as exc:
                logger.warning("trace.error", run_name=span_name, error=str(exc))
                raise

        return sync_wrapper

    return decorator
