# tests/eval/conftest.py

"""Fixtures for memory spine eval (including opt-in live LLM)."""

from __future__ import annotations

import pytest

from palatium_ai.core.config import get_settings
from palatium_ai.infrastructure.llm.factory import LLMClientFactory


@pytest.fixture
def live_llm():
    """LLMPort from project settings (env/.env)."""
    get_settings.cache_clear()
    settings = get_settings()
    return LLMClientFactory(settings).get_client()
