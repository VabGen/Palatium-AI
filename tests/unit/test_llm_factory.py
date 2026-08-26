"""Unit tests for LLMClientFactory agent-scoped clients."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from palatium_ai.core.config.llm import TierBinding
from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.infrastructure.llm.factory import LLMClientFactory
from tests.conftest import FakeLLMPort


def _settings(
    *,
    default_provider: str = "openai",
    tier_binding: TierBinding | None = None,
    fallback_providers: tuple[str, ...] = (),
) -> SimpleNamespace:
    binding = tier_binding or TierBinding(provider=None, model=None)

    def _chain(primary: str) -> tuple[str, ...]:
        chain: list[str] = []
        for name in (primary, *fallback_providers):
            if name and name not in chain:
                chain.append(name)
        return tuple(chain)

    llm = SimpleNamespace(
        default_provider=default_provider,
        resolve_tier_binding=lambda _tier: binding,
        build_provider_chain=_chain,
        fallback_provider_list=fallback_providers,
    )
    return SimpleNamespace(llm=llm)


def _agent_config(**overrides: Any) -> AgentConfig:
    base: dict[str, Any] = {
        "name": "test_agent",
        "role": "critic",
        "model_tier": "mid",
    }
    base.update(overrides)
    return AgentConfig(**base)


def test_get_client_for_agent_uses_agent_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """llm_provider on AgentConfig must select that provider client."""
    factory = LLMClientFactory(settings=_settings())  # type: ignore[arg-type]
    captured: list[str | None] = []
    fake = FakeLLMPort("{}")

    def _fake_get_client(provider_name: str | None = None) -> FakeLLMPort:
        captured.append(provider_name)
        return fake

    monkeypatch.setattr(factory, "get_client", _fake_get_client)

    client = factory.get_client_for_agent(_agent_config(llm_provider="ollama"))
    assert client is fake
    assert captured == ["ollama"]


def test_get_client_for_agent_falls_back_to_default_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without llm_provider / tier provider, factory must use default_provider."""
    factory = LLMClientFactory(settings=_settings(default_provider="qwen"))  # type: ignore[arg-type]
    captured: list[str | None] = []
    fake = FakeLLMPort("{}")

    def _fake_get_client(provider_name: str | None = None) -> FakeLLMPort:
        captured.append(provider_name)
        return fake

    monkeypatch.setattr(factory, "get_client", _fake_get_client)

    client = factory.get_client_for_agent(_agent_config())
    assert client is fake
    assert captured == ["qwen"]


def test_get_client_for_agent_uses_tier_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier provider wins over default when agent has no llm_provider."""
    factory = LLMClientFactory(
        settings=_settings(
            default_provider="openai",
            tier_binding=TierBinding(provider="ollama", model="gpt-oss:20b-cloud"),
        )
    )  # type: ignore[arg-type]
    captured: list[str | None] = []
    fake = FakeLLMPort("{}")

    def _fake_get_client(provider_name: str | None = None) -> FakeLLMPort:
        captured.append(provider_name)
        return fake

    monkeypatch.setattr(factory, "get_client", _fake_get_client)

    client = factory.get_client_for_agent(_agent_config(model_tier="small"))
    assert client is not None
    assert captured == ["ollama"]


@pytest.mark.asyncio
async def test_get_client_for_agent_applies_tier_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier model becomes default generate() model when agent has no llm_model."""
    factory = LLMClientFactory(
        settings=_settings(
            default_provider="openai",
            tier_binding=TierBinding(provider="anthropic", model="claude-tier"),
        )
    )  # type: ignore[arg-type]
    fake = FakeLLMPort("{}")
    captured: list[str | None] = []

    def _fake_get_client(provider_name: str | None = None) -> FakeLLMPort:
        captured.append(provider_name)
        return fake

    monkeypatch.setattr(factory, "get_client", _fake_get_client)

    client = factory.get_client_for_agent(_agent_config(model_tier="frontier"))
    result = await client.generate([ChatMessage(role="user", content="hi")])
    assert captured == ["anthropic"]
    assert result.model == "claude-tier"


@pytest.mark.asyncio
async def test_get_client_for_agent_applies_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """llm_model on AgentConfig must become the default model for generate()."""
    factory = LLMClientFactory(settings=_settings())  # type: ignore[arg-type]
    fake = FakeLLMPort("{}")

    monkeypatch.setattr(factory, "get_client", lambda provider_name=None: fake)

    client = factory.get_client_for_agent(_agent_config(llm_model="custom-model"))
    result = await client.generate([ChatMessage(role="user", content="hi")])
    assert result.model == "custom-model"


@pytest.mark.asyncio
async def test_agent_provider_wins_over_tier_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit AgentConfig.llm_provider beats tier provider."""
    factory = LLMClientFactory(settings=_settings(tier_binding=TierBinding(provider="ollama", model="tier-model")))  # type: ignore[arg-type]
    captured: list[str | None] = []
    fake = FakeLLMPort("{}")

    def _fake_get_client(provider_name: str | None = None) -> FakeLLMPort:
        captured.append(provider_name)
        return fake

    monkeypatch.setattr(factory, "get_client", _fake_get_client)

    client = factory.get_client_for_agent(
        _agent_config(llm_provider="openai", llm_model="agent-model", model_tier="small")
    )
    result = await client.generate([ChatMessage(role="user", content="hi")])
    assert captured == ["openai"]
    assert result.model == "agent-model"


@pytest.mark.asyncio
async def test_get_client_for_agent_explicit_model_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit generate(model=...) must override AgentConfig.llm_model."""
    factory = LLMClientFactory(settings=_settings())  # type: ignore[arg-type]
    fake = FakeLLMPort("{}")

    monkeypatch.setattr(factory, "get_client", lambda provider_name=None: fake)

    client = factory.get_client_for_agent(_agent_config(llm_model="config-model"))
    result = await client.generate(
        [ChatMessage(role="user", content="hi")],
        model="call-model",
    )
    assert result.model == "call-model"


def test_fallback_skips_provider_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI listed as fallback but missing key must not enter the adapter chain."""

    def _chain(primary: str) -> tuple[str, ...]:
        return (primary, "openai")

    llm = SimpleNamespace(
        default_provider="ollama",
        resolve_tier_binding=lambda _tier: TierBinding(provider=None, model=None),
        build_provider_chain=_chain,
        fallback_provider_list=("openai",),
        ollama=SimpleNamespace(get_api_key=lambda: "ollama-key"),
        openai=SimpleNamespace(get_api_key=lambda: None),
    )
    factory = LLMClientFactory(settings=SimpleNamespace(llm=llm))  # type: ignore[arg-type]
    captured: list[str | None] = []
    fake = FakeLLMPort("{}")

    def _fake_get_client(provider_name: str | None = None) -> FakeLLMPort:
        captured.append(provider_name)
        return fake

    monkeypatch.setattr(factory, "get_client", _fake_get_client)

    client = factory.get_client_for_agent(_agent_config(llm_provider="ollama"))
    assert client is fake
    assert captured == ["ollama"]
