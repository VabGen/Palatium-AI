# src/palatium_ai/presentation/middleware/tracing.py

"""HTTP tracing: trace_id propagation, context vars, request spans (040)."""

from __future__ import annotations

import time

from typing import TYPE_CHECKING

import structlog

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from palatium_ai.core.logging.context import trace_id_var
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.otel import get_tracer
from palatium_ai.core.observability.span_names import HTTP_REQUEST
from palatium_ai.core.observability.trace_context import resolve_trace_id, trace_id_header_name

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

logger = structlog.get_logger(__name__)


class TracingMiddleware(BaseHTTPMiddleware):
    """Mint/propagate trace_id and record per-request latency."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Bind trace context for the request lifetime."""
        trace_id = resolve_trace_id(
            header_value=request.headers.get(trace_id_header_name()),
            traceparent=request.headers.get("traceparent"),
        )
        token = trace_id_var.set(trace_id)
        request.state.trace_id = trace_id
        started = time.perf_counter()
        tracer = get_tracer()
        span_cm = tracer.start_as_current_span(HTTP_REQUEST) if tracer is not None else None
        try:
            if span_cm is not None:
                with span_cm:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        except Exception:
            logger.warning("http.request.failed", path=request.url.path, method=request.method, trace_id=trace_id)
            raise
        finally:
            duration = time.perf_counter() - started
            agent_metrics.record_node_execution(
                "http",
                request.method,
                duration_seconds=duration,
            )
            trace_id_var.reset(token)

        response.headers[trace_id_header_name()] = trace_id
        return response
