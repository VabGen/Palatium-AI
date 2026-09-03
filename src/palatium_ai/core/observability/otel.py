# src/palatium_ai/core/observability/otel.py

"""OpenTelemetry bootstrap (040) — primary tracing; LangSmith secondary via env."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from opentelemetry.trace import Tracer

    from palatium_ai.core.config.observability import ObservabilityConfig

logger = structlog.get_logger(__name__)

_TRACER: Tracer | None = None
_OTEL_ENABLED = False


def setup_otel_tracing(observability: ObservabilityConfig, *, service_name: str) -> bool:
    """Configure OTel TracerProvider when OTEL_ENDPOINT is set. Returns True if enabled."""
    global _TRACER, _OTEL_ENABLED

    endpoint = (observability.otel_endpoint or "").strip()
    if not endpoint:
        logger.info("otel.tracing.disabled", reason="OTEL_ENDPOINT unset")
        _OTEL_ENABLED = False
        _TRACER = None
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:  # pragma: no cover
        logger.warning("otel.tracing.disabled", reason="opentelemetry packages not installed")
        _OTEL_ENABLED = False
        _TRACER = None
        return False

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _TRACER = trace.get_tracer("palatium_ai")
    _OTEL_ENABLED = True
    logger.info("otel.tracing.enabled", endpoint=endpoint, service=service_name)
    return True


def get_tracer() -> Tracer | None:
    """Return OTel tracer when bootstrap succeeded."""
    return _TRACER


def otel_tracing_enabled() -> bool:
    return _OTEL_ENABLED
