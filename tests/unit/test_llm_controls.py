# tests/unit/test_llm_controls.py

"""reasoning_effort + verbosity dials: policies and LiteLLM wiring (2026)."""

from __future__ import annotations

import pytest

from palatium_ai.application.agents.harness import Harness, _resolve_llm_controls
from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.domain.policies.reasoning_effort import ReasoningEffortPolicy
from palatium_ai.domain.policies.verbosity import VerbosityPolicy
from palatium_ai.infrastructure.llm.litellm_adapter import LiteLLMAdapter
from tests.conftest import FakeLLMPort


@pytest.mark.parametrize(
    "tier,expected",
    (
        ("nano", "low"),
        ("small", "low"),
        ("mid", "medium"),
        ("frontier", "high"),
        ("deep_reasoning", "high"),
    ),
)
def test_reasoning_effort_follows_model_tier(tier: str, expected: str) -> None:
    assert ReasoningEffortPolicy.for_model_tier(tier) == expected


@pytest.mark.parametrize(
    "budget,expected",
    (
        ("minimal", "low"),
        ("standard", "medium"),
        ("detailed", "high"),
        (None, "medium"),
    ),
)
def test_verbosity_budget_maps_to_api_dial(budget: str | None, expected: str) -> None:
    assert VerbosityPolicy.to_api_verbosity(budget) == expected


def test_resolve_llm_controls_prefers_call_override_then_config_then_tier() -> None:
    config = AgentConfig(
        name="t",
        role="researcher",
        model_tier="mid",
        reasoning_effort="low",
        verbosity="high",
    )
    effort, verb = _resolve_llm_controls(config, reasoning_effort="max", verbosity="low")
    assert effort == "max"
    assert verb == "low"

    effort, verb = _resolve_llm_controls(config, reasoning_effort=None, verbosity=None)
    assert effort == "low"
    assert verb == "high"

    bare = AgentConfig(name="t", role="intent_classifier", model_tier="nano")
    effort, verb = _resolve_llm_controls(bare, reasoning_effort=None, verbosity=None)
    assert effort == "low"
    assert verb is None


@pytest.mark.asyncio()
async def test_harness_forwards_effort_and_verbosity_to_llm_port() -> None:
    llm = FakeLLMPort('{"ok":true}')
    harness = Harness(llm=llm)
    config = AgentConfig(name="t", role="researcher", model_tier="frontier")

    await harness.call_llm(
        config,
        [ChatMessage(role="user", content="hi")],
        verbosity="high",
    )

    assert llm.last_kwargs["reasoning_effort"] == "high"
    assert llm.last_kwargs["verbosity"] == "high"


@pytest.mark.asyncio()
async def test_litellm_generate_forwards_dials(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from palatium_ai.core.config.llm.openai import OpenAILLMConfig

    captured: dict[str, object] = {}

    async def _fake_acompletion(**params: object) -> object:
        captured.update(params)
        return SimpleNamespace(choices=[], model="gpt-test", usage=None)

    monkeypatch.setattr("palatium_ai.infrastructure.llm.litellm_adapter.acompletion", _fake_acompletion)
    adapter = LiteLLMAdapter(OpenAILLMConfig.model_validate({"OPENAI_API_KEY": "k", "OPENAI_TIMEOUT": "42"}))
    await adapter.generate(
        [ChatMessage(role="user", content="hi")],
        model="gpt-test",
        max_tokens=128,
        reasoning_effort="medium",
        verbosity="low",
    )
    assert captured["reasoning_effort"] == "medium"
    assert captured["verbosity"] == "low"
    assert captured["max_tokens"] == 128


@pytest.mark.asyncio()
async def test_litellm_anthropic_omits_verbosity_keeps_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anthropic rejects verbosity; adapter must omit it while keeping reasoning_effort."""
    from types import SimpleNamespace

    from pydantic import SecretStr

    from palatium_ai.core.config.llm.anthropic import AnthropicLLMConfig

    captured: dict[str, object] = {}
    dropped: list[dict[str, object]] = []

    async def _fake_acompletion(**params: object) -> object:
        captured.update(params)
        return SimpleNamespace(choices=[], model="claude-opus-4-6", usage=None)

    def _fake_debug(event: str, **kwargs: object) -> None:
        if event == "llm.verbosity.dropped":
            dropped.append({"event": event, **kwargs})

    monkeypatch.setattr("palatium_ai.infrastructure.llm.litellm_adapter.acompletion", _fake_acompletion)
    monkeypatch.setattr("palatium_ai.infrastructure.llm.litellm_adapter.logger.debug", _fake_debug)
    adapter = LiteLLMAdapter(
        AnthropicLLMConfig(api_key=SecretStr("k"), default_model="claude-opus-4-6"),
    )
    await adapter.generate(
        [ChatMessage(role="user", content="hi")],
        model="claude-opus-4-6",
        max_tokens=32,
        reasoning_effort="high",
        verbosity="low",
    )
    assert captured["reasoning_effort"] == "high"
    assert "verbosity" not in captured
    assert dropped == [
        {
            "event": "llm.verbosity.dropped",
            "provider": "anthropic",
            "verbosity": "low",
            "reason": "unsupported_by_provider",
        }
    ]
