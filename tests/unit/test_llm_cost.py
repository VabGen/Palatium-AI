"""Unit tests for LiteLLM usage parsing and cost estimate."""

from __future__ import annotations

from types import SimpleNamespace

from palatium_ai.infrastructure.llm.cost import estimate_completion_cost_usd
from palatium_ai.infrastructure.llm.litellm_adapter import _parse_usage


def test_parse_usage_from_object() -> None:
    usage = _parse_usage(SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15))
    assert usage.prompt_tokens == 10
    assert usage.completion_tokens == 5
    assert usage.total_tokens == 15


def test_parse_usage_from_dict() -> None:
    usage = _parse_usage({"prompt_tokens": 7, "completion_tokens": 3})
    assert usage.prompt_tokens == 7
    assert usage.completion_tokens == 3
    assert usage.total_tokens == 10


def test_parse_usage_none() -> None:
    usage = _parse_usage(None)
    assert usage.total_tokens == 0


def test_estimate_cost_known_model() -> None:
    cost = estimate_completion_cost_usd(
        model="gpt-4o-mini",
        prompt_tokens=100,
        completion_tokens=50,
    )
    assert cost > 0.0


def test_estimate_cost_unknown_model_is_zero() -> None:
    cost = estimate_completion_cost_usd(
        model="local-ollama/unknown-model-xyz",
        prompt_tokens=100,
        completion_tokens=50,
    )
    assert cost == 0.0
