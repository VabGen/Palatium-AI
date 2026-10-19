# src/palatium_ai/core/observability/__init__.py

"""Observability: tracing, metrics, audit."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .audit import get_audit_logger
from .langsmith_env import apply_langsmith_env
from .metrics import AgentMetrics, agent_metrics
from .otel import setup_otel_tracing
from .tracing import traceable

if TYPE_CHECKING:
    from palatium_ai.core.config.settings import Settings


def setup_observability(settings: Settings) -> None:
    """Bootstrap OTel (primary) + LangSmith env (secondary, 040)."""
    import structlog

    from palatium_ai.core.observability.adaptive_grounding import (
        warn_if_enabled_but_zero_rollout,
    )
    from palatium_ai.core.observability.formatter_rollout import (
        warn_if_schema_first_but_zero_rollout,
    )

    setup_otel_tracing(settings.observability, service_name=settings.app.name)
    apply_langsmith_env(settings.observability)
    warn_if_enabled_but_zero_rollout(settings)
    warn_if_schema_first_but_zero_rollout(
        settings.formatter.formatter_mode,
        settings.formatter.formatter_rollout_pct,
    )
    if settings.observability.otel_capture_raw_query:
        # ``app.environment`` is a validated Literal, so "development" is the only
        # non-production value to compare against — no further normalisation needed.
        log = structlog.get_logger(__name__)
        if settings.app.environment == "development":
            log.warning("otel.capture_raw_query.enabled", environment=settings.app.environment)
        else:
            log.warning(
                "otel.capture_raw_query.misconfigured",
                environment=settings.app.environment,
                message="OTEL_CAPTURE_RAW_QUERY must stay false outside development",
            )


__all__ = [
    "AgentMetrics",
    "agent_metrics",
    "apply_langsmith_env",
    "get_audit_logger",
    "setup_observability",
    "setup_otel_tracing",
    "traceable",
]
