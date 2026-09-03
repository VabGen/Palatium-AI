# src/palatium_ai/infrastructure/web/factory.py

"""WebSearchPort factory — stub vs live HTTP (070)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.core.logging import logger
from palatium_ai.core.resilience.circuit import ConsecutiveFailureCircuit
from palatium_ai.domain.web.port import WebSearchPort
from palatium_ai.infrastructure.web.stub_web_search_port import StubWebSearchPort

if TYPE_CHECKING:
    from palatium_ai.core.config.settings import Settings


def build_web_search_port(settings: Settings) -> WebSearchPort:
    """Select web search backend; fail open to stub when misconfigured."""
    if settings.web.backend != "http":
        return StubWebSearchPort()

    provider = settings.web.provider
    timeout = settings.web.timeout_seconds
    api_key = settings.web.api_key.get_secret_value() if settings.web.api_key is not None else ""

    try:
        from palatium_ai.infrastructure.web.http_web_search_port import (
            BraveSearchTransport,
            DuckDuckGoInstantAnswerTransport,
            HttpWebSearchPort,
        )

        if provider == "brave":
            transport: BraveSearchTransport | DuckDuckGoInstantAnswerTransport = BraveSearchTransport(
                api_key=api_key, timeout_seconds=timeout
            )
        else:
            transport = DuckDuckGoInstantAnswerTransport(timeout_seconds=timeout)
        logger.info(
            "WebSearchPort: HTTP",
            provider=provider,
            retry_attempts=settings.web.retry_attempts,
            circuit_failures=settings.web.circuit_failures_to_open,
        )
        return HttpWebSearchPort(
            transport,
            provider=provider,
            circuit=ConsecutiveFailureCircuit(
                failures_to_open=settings.web.circuit_failures_to_open,
                open_seconds=settings.web.circuit_open_seconds,
            ),
            retry_attempts=settings.web.retry_attempts,
            retry_delay_seconds=settings.web.retry_delay_seconds,
        )
    except (ImportError, ValueError) as exc:
        logger.warning("HTTP web search unavailable; using stub", error=str(exc))
        return StubWebSearchPort()
