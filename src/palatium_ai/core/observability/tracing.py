# src/palatium_ai/core/observability/tracing.py

"""OTel-primary tracing with structlog fallback (040)."""

from __future__ import annotations

import inspect

from collections.abc import Awaitable, Callable, Mapping, Sequence
from functools import wraps
from typing import TYPE_CHECKING, ParamSpec, TypeVar, cast

import structlog

from palatium_ai.core.observability.otel import get_tracer

if TYPE_CHECKING:
    from palatium_ai.domain.llm.models import LLMUsage

logger = structlog.get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def add_gen_ai_attributes(
    span: object,
    *,
    model: str,
    usage: LLMUsage,
    cost_usd: float,
    finish_reason: str | None,
) -> None:
    """Add OpenTelemetry GenAI Semantic Conventions attributes (Phase 3)."""
    set_attributes = getattr(span, "set_attributes", None)
    if not callable(set_attributes):
        return
    reasons: Sequence[str] = (finish_reason,) if finish_reason else ()
    set_attributes(
        {
            "gen_ai.system": "litellm",
            "gen_ai.request.model": model,
            "gen_ai.usage.input_tokens": usage.prompt_tokens,
            "gen_ai.usage.output_tokens": usage.completion_tokens,
            "gen_ai.usage.cost_usd": cost_usd,
            "gen_ai.response.finish_reasons": list(reasons),
        }
    )


def add_span_event(
    name: str,
    attributes: Mapping[str, str | int | float | bool] | None = None,
) -> None:
    """Attach an event to the current span when tracing is recording (040).

    Events are the right shape for "this happened once, on this call" facts (a
    PII image was forwarded, a fallback fired): they stay off the metric vocabulary
    and need no new counter name. A no-op without an active recording span, so the
    caller never has to guard the whole code path.
    """
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover - otel is optional in minimal installs
        return
    span = trace.get_current_span()
    if span is None or not span.is_recording():  # pragma: no cover - depends on exporter
        return
    span.add_event(name, attributes=dict(attributes or {}))


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

        # ``asyncio.iscoroutinefunction`` is deprecated since 3.14 and removed in
        # 3.16; ``inspect`` is the supported equivalent for plain async defs (050).
        if inspect.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]  # overload декоратора; mypy не сводит (017)

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
