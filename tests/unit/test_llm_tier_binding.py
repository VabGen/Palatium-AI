"""Unit tests for LLMConfig tier provider+model bindings."""

from __future__ import annotations

import pytest

from palatium_ai.core.config.llm import LLMConfig


def test_resolve_tier_binding_empty() -> None:
    cfg = LLMConfig(_env_file=None, default_provider="ollama")  # type: ignore[call-arg]
    binding = cfg.resolve_tier_binding("small")
    assert binding.provider is None
    assert binding.model is None


def test_resolve_tier_binding_pair() -> None:
    cfg = LLMConfig(  # type: ignore[call-arg]
        _env_file=None,
        default_provider="ollama",
        tier_small_provider="openai",
        tier_small_model="gpt-4o-mini",
    )
    binding = cfg.resolve_tier_binding("small")
    assert binding.provider == "openai"
    assert binding.model == "gpt-4o-mini"


def test_invalid_tier_provider_rejected() -> None:
    with pytest.raises(ValueError, match="LLM_TIER_SMALL_PROVIDER"):
        LLMConfig(  # type: ignore[call-arg]
            _env_file=None,
            default_provider="ollama",
            tier_small_provider="not-a-provider",
        )
