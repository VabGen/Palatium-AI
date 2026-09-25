"""Per-provider LLM circuit breaker (P1-9, 020).

Without a breaker, a dead primary provider costs the full provider timeout on *every*
call before the fallback chain moves on. These tests pin the fast-skip behaviour and
the half-open recovery path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from palatium_ai.core.config.llm import TierBinding
from palatium_ai.core.resilience import CircuitOpenError, ConsecutiveFailureCircuit
from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.llm.models import ChatMessage, LLMCompletion, LLMStreamDelta
from palatium_ai.infrastructure.llm.factory import LLMClientFactory


class _RecordingPort:
    """Minimal LLMPort that fails or succeeds on demand and counts calls."""

    def __init__(self, *, fail: bool = False, content: str = "ok") -> None:
        self.fail = fail
        self.content = content
        self.calls = 0

    async def generate(self, messages: list[ChatMessage], **kwargs: Any) -> LLMCompletion:
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider down")
        return LLMCompletion(content=self.content, model="m")


class _RecordingStreamPort(_RecordingPort):
    async def generate_stream(self, messages: list[ChatMessage], **kwargs: Any) -> AsyncIterator[LLMStreamDelta]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider down")
        yield LLMStreamDelta(content=self.content)


def _settings(
    *,
    chain: tuple[str, ...],
    circuit_failures_to_open: int = 2,
    circuit_open_seconds: float = 30.0,
    keys: dict[str, str | None] | None = None,
) -> SimpleNamespace:
    """Settings stub with a fixed provider chain and observability thresholds."""
    resolved_keys = keys or {}

    def _chain(_primary: str) -> tuple[str, ...]:
        return chain

    llm = SimpleNamespace(
        default_provider=chain[0],
        resolve_tier_binding=lambda _tier: TierBinding(provider=None, model=None),
        build_provider_chain=_chain,
        fallback_provider_list=chain[1:],
        **{name: SimpleNamespace(get_api_key=lambda name=name: resolved_keys.get(name, "key")) for name in chain},
    )
    observability = SimpleNamespace(
        circuit_failures_to_open=circuit_failures_to_open,
        circuit_open_seconds=circuit_open_seconds,
    )
    return SimpleNamespace(
        llm=llm,
        observability=observability,
        app=SimpleNamespace(environment="development"),
    )


def _agent_config(**overrides: Any) -> AgentConfig:
    base: dict[str, Any] = {"name": "test_agent", "role": "critic", "model_tier": "mid"}
    base.update(overrides)
    return AgentConfig(**base)


def _factory_with_ports(
    ports: dict[str, _RecordingPort],
    *,
    circuit_failures_to_open: int = 2,
) -> LLMClientFactory:
    chain = tuple(ports)
    factory = LLMClientFactory(
        settings=_settings(chain=chain, circuit_failures_to_open=circuit_failures_to_open)  # type: ignore[arg-type]
    )
    factory.get_client = lambda provider_name=None: ports[provider_name or chain[0]]  # type: ignore[method-assign]
    return factory


@pytest.mark.asyncio
async def test_primary_is_skipped_without_calling_it_once_circuit_opens() -> None:
    """The whole point: after the breaker opens, the dead provider is not called."""
    primary = _RecordingPort(fail=True)
    secondary = _RecordingPort(content="from-secondary")
    factory = _factory_with_ports({"openai": primary, "anthropic": secondary}, circuit_failures_to_open=2)

    client = factory.get_client_for_agent(_agent_config())
    message = [ChatMessage(role="user", content="hi")]

    # Two calls to trip the breaker; each still falls back successfully.
    for _ in range(2):
        assert (await client.generate(message)).content == "from-secondary"
    assert primary.calls == 2

    # Third call: breaker open → primary is skipped entirely.
    assert (await client.generate(message)).content == "from-secondary"
    assert primary.calls == 2, "open circuit must not be called again"


@pytest.mark.asyncio
async def test_successful_provider_resets_failure_counter() -> None:
    """A transient blip must not accumulate toward the threshold."""
    flaky = _RecordingPort(fail=True)
    secondary = _RecordingPort(content="secondary")
    factory = _factory_with_ports({"openai": flaky, "anthropic": secondary}, circuit_failures_to_open=3)

    client = factory.get_client_for_agent(_agent_config())
    message = [ChatMessage(role="user", content="hi")]

    await client.generate(message)
    assert flaky.calls == 1

    flaky.fail = False
    assert (await client.generate(message)).content == "ok"
    assert flaky.calls == 2

    # Counter was reset, so failures start from scratch again.
    flaky.fail = True
    await client.generate(message)
    assert flaky.calls == 3
    # Only one failure since the reset → circuit still closed → still called.
    await client.generate(message)
    assert flaky.calls == 4


@pytest.mark.asyncio
async def test_all_circuits_open_raises_circuit_open_error() -> None:
    """Every provider down must produce a fast, typed failure — not a generic one."""
    factory = _factory_with_ports(
        {"openai": _RecordingPort(fail=True), "anthropic": _RecordingPort(fail=True)},
        circuit_failures_to_open=1,
    )
    client = factory.get_client_for_agent(_agent_config())
    message = [ChatMessage(role="user", content="hi")]

    with pytest.raises(RuntimeError, match="fallback chain failed"):
        await client.generate(message)

    with pytest.raises(CircuitOpenError) as excinfo:
        await client.generate(message)
    assert excinfo.value.name.startswith("llm:")
    assert excinfo.value.retry_after_seconds > 0


@pytest.mark.asyncio
async def test_half_open_probe_recovers_provider() -> None:
    """open → half_open → closed: a recovered provider must be used again."""
    primary = _RecordingPort(fail=True)
    secondary = _RecordingPort(content="secondary")
    factory = _factory_with_ports({"openai": primary, "anthropic": secondary}, circuit_failures_to_open=1)

    client = factory.get_client_for_agent(_agent_config())
    message = [ChatMessage(role="user", content="hi")]
    circuit = factory._circuit_for("openai")

    await client.generate(message)  # trips the breaker
    assert primary.calls == 1
    assert circuit.state == "open"

    # Simulate the cooldown elapsing without patching the global clock.
    circuit.open_until = 0.0
    primary.fail = False

    assert (await client.generate(message)).content == "ok"
    assert primary.calls == 2
    assert circuit.state == "closed"


@pytest.mark.asyncio
async def test_streaming_path_records_circuit_failures() -> None:
    primary = _RecordingStreamPort(fail=True)
    secondary = _RecordingStreamPort(content="streamed")
    factory = _factory_with_ports({"openai": primary, "anthropic": secondary}, circuit_failures_to_open=1)

    client = factory.get_client_for_agent(_agent_config())
    message = [ChatMessage(role="user", content="hi")]

    first = [delta.content async for delta in client.generate_stream(message)]
    assert first == ["streamed"]

    # Breaker open now → primary skipped.
    second = [delta.content async for delta in client.generate_stream(message)]
    assert second == ["streamed"]
    assert primary.calls == 1


def test_circuits_are_shared_across_agents_on_one_factory() -> None:
    """Provider health is process-wide, so one agent's failures must protect others."""
    factory = _factory_with_ports({"openai": _RecordingPort(), "anthropic": _RecordingPort()})

    first = factory.get_client_for_agent(_agent_config(name="a"))
    second = factory.get_client_for_agent(_agent_config(name="b"))

    assert first._circuits["openai"] is second._circuits["openai"]
    assert first._circuits["openai"] is factory._circuit_for("openai")


def test_circuit_thresholds_come_from_observability_config() -> None:
    """CIRCUIT_FAILURES_TO_OPEN / CIRCUIT_OPEN_SECONDS must not be dead config."""
    factory = LLMClientFactory(
        settings=_settings(  # type: ignore[arg-type]
            chain=("openai", "anthropic"),
            circuit_failures_to_open=7,
            circuit_open_seconds=99.0,
        )
    )
    circuit = factory._circuit_for("openai")
    assert circuit.failures_to_open == 7
    assert circuit.open_seconds == 99.0


def test_circuit_defaults_when_settings_lack_observability() -> None:
    """Ad-hoc factories (tests, scripts) must still get a working breaker."""
    settings = SimpleNamespace(llm=SimpleNamespace())
    factory = LLMClientFactory(settings=settings)  # type: ignore[arg-type]
    circuit = factory._circuit_for("openai")
    assert isinstance(circuit, ConsecutiveFailureCircuit)
    assert circuit.failures_to_open == 3
