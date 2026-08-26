# tests/unit/test_week2_sla.py

"""Week 2: LLM fallback chain, MCP/call circuit, cost budget, node circuit."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from palatium_ai.application.orchestration.graph import reset_node_circuits_for_tests
from palatium_ai.application.services.cost_budget import CostBudgetExceededError, CostBudgetService
from palatium_ai.core.config.llm import TierBinding
from palatium_ai.core.observability.turn_tokens import turn_token_usage
from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.llm.models import ChatMessage, LLMCompletion
from palatium_ai.domain.mcp.models import MCPToolCall, MCPToolResult
from palatium_ai.infrastructure.llm.factory import LLMClientFactory
from palatium_ai.infrastructure.mcp.circuit import McpServerCircuit
from palatium_ai.infrastructure.resilience.circuit import CircuitOpenError, ConsecutiveFailureCircuit
from tests.conftest import FakeLLMPort


class _FailThenOk(FakeLLMPort):
    def __init__(self, fail_times: int, content: str = "ok") -> None:
        super().__init__(content)
        self._fail_times = fail_times
        self.attempts = 0

    async def generate(self, messages: list[ChatMessage], **kwargs: Any) -> LLMCompletion:
        self.attempts += 1
        if self.attempts <= self._fail_times:
            raise RuntimeError(f"provider down #{self.attempts}")
        return await super().generate(messages, **kwargs)


def _settings_with_fallback(*, fallback: tuple[str, ...] = ("anthropic",)) -> SimpleNamespace:
    def _chain(primary: str) -> tuple[str, ...]:
        out: list[str] = []
        for name in (primary, *fallback):
            if name not in out:
                out.append(name)
        return tuple(out)

    llm = SimpleNamespace(
        default_provider="openai",
        resolve_tier_binding=lambda _tier: TierBinding(provider=None, model=None),
        build_provider_chain=_chain,
        fallback_provider_list=fallback,
    )
    return SimpleNamespace(llm=llm)


@pytest.mark.asyncio
async def test_fallback_chain_uses_second_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = LLMClientFactory(settings=_settings_with_fallback())  # type: ignore[arg-type]
    primary = _FailThenOk(fail_times=99, content="primary")
    secondary = FakeLLMPort("secondary-ok")

    def _get_client(provider_name: str | None = None) -> FakeLLMPort:
        if provider_name == "openai":
            return primary
        return secondary

    monkeypatch.setattr(factory, "get_client", _get_client)
    client = factory.get_client_for_agent(AgentConfig(name="x", role="critic", model_tier="mid"))
    result = await client.generate([ChatMessage(role="user", content="hi")])
    assert result.content == "secondary-ok"
    assert primary.attempts == 1


def test_mcp_circuit_opens_after_three_call_failures() -> None:
    circuit = McpServerCircuit()
    now = 1000.0
    assert not circuit.is_open(now)
    circuit.record_failure(now)
    circuit.record_failure(now)
    assert not circuit.is_open(now)
    circuit.record_failure(now)
    assert circuit.is_open(now)


@pytest.mark.asyncio
async def test_registry_call_tool_trips_circuit_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from palatium_ai.domain.mcp.models import MCPToolDescriptor
    from palatium_ai.infrastructure.mcp.base import MCPJsonRpcClient
    from palatium_ai.infrastructure.mcp.registry import MCPCircuitOpenError, MCPRegistry

    settings = SimpleNamespace(mcp=SimpleNamespace(servers={"edms": "http://edms"}, cache_ttl_seconds=60))
    reg = MCPRegistry(settings=settings)  # type: ignore[arg-type]
    reg._servers = {"edms": "http://edms"}
    reg._initialized = True

    class _Client:
        async def list_tools(self) -> list[MCPToolDescriptor]:
            return [
                MCPToolDescriptor(
                    name="search_documents",
                    description="",
                    inputSchema={"type": "object", "properties": {}},
                    annotations={"readOnlyHint": True},
                )
            ]

        async def call_tool(self, tool_call: MCPToolCall) -> MCPToolResult:
            raise httpx.ConnectError("boom")

    monkeypatch.setattr(reg, "get_client", lambda _name: _Client())
    monkeypatch.setattr(MCPJsonRpcClient, "validate_arguments", staticmethod(lambda *_a, **_k: None))

    await reg.list_tools("edms")
    for _ in range(3):
        with pytest.raises(httpx.HTTPError):
            await reg.call_tool(
                "edms",
                MCPToolCall(name="search_documents", arguments={}),
            )

    with pytest.raises(MCPCircuitOpenError):
        await reg.call_tool(
            "edms",
            MCPToolCall(name="search_documents", arguments={}),
        )


def test_turn_cost_budget_fail_closed() -> None:
    budget = CostBudgetService(turn_budget_usd=0.01)
    with turn_token_usage() as tokens:
        tokens.record(
            agent="a",
            model="m",
            prompt_tokens=10,
            completion_tokens=10,
            cost_usd=0.02,
        )
        with pytest.raises(CostBudgetExceededError):
            budget.assert_turn_allows_call()


@pytest.mark.asyncio
async def test_daily_cost_budget_fail_closed() -> None:
    budget = CostBudgetService(daily_budget_usd=1.0)
    await budget.record_turn_cost(tenant_key="user-1", cost_usd=1.5)
    with pytest.raises(CostBudgetExceededError):
        await budget.assert_daily_allows_turn(tenant_key="user-1")


def test_node_circuit_opens() -> None:
    reset_node_circuits_for_tests()
    circuit = ConsecutiveFailureCircuit()
    now = 1.0
    circuit.record_failure(now)
    circuit.record_failure(now)
    circuit.record_failure(now)
    assert circuit.is_open(now)
    with pytest.raises(CircuitOpenError):
        raise CircuitOpenError("researcher", retry_after_seconds=30)
