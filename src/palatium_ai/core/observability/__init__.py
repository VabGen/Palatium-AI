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
    setup_otel_tracing(settings.observability, service_name=settings.app.name)
    apply_langsmith_env(settings.observability)


__all__ = [
    "traceable",
    "AgentMetrics",
    "agent_metrics",
    "get_audit_logger",
    "setup_observability",
    "setup_otel_tracing",
    "apply_langsmith_env",
]
