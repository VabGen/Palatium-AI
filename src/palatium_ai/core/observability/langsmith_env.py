# src/palatium_ai/core/observability/langsmith_env.py

"""Apply ObservabilityConfig to process env for LangSmith/LangChain tracing."""

from __future__ import annotations

import os

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from palatium_ai.core.config.observability import ObservabilityConfig

logger = structlog.get_logger(__name__)


def apply_langsmith_env(observability: ObservabilityConfig) -> None:
    """
    Sync LANGCHAIN_* env from settings.

    Tracing stays off when API key is missing to avoid noisy 403s against LangSmith.
    """
    project = observability.langchain_project.strip() or "palatium-ai"
    os.environ["LANGCHAIN_PROJECT"] = project

    key = ""
    if observability.langchain_api_key is not None:
        key = observability.langchain_api_key.get_secret_value().strip()

    if observability.langchain_tracing_v2 and key and not key.startswith("your_"):
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = key
        logger.info("LangSmith tracing enabled", project=project)
        return

    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    if observability.langchain_tracing_v2 and not key:
        logger.warning("LangSmith tracing disabled: LANGCHAIN_API_KEY missing")
    elif observability.langchain_tracing_v2 and key.startswith("your_"):
        logger.warning("LangSmith tracing disabled: placeholder LANGCHAIN_API_KEY")
