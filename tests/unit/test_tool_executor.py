# tests/unit/test_tool_executor.py

"""Тесты RBAC ToolExecutor."""

from __future__ import annotations

import pytest

from pydantic import BaseModel

import palatium_ai.application.tools.executor as executor_module

from palatium_ai.application.tools.executor import ToolExecutor, ToolRbacDenied
from palatium_ai.core.exceptions import ToolNotAllowedError
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.agents.contracts import AgentContext


class _Params(BaseModel):
    query: str


class _Result(BaseModel):
    value: str


async def _handler(params: _Params) -> _Result:
    return _Result(value=params.query.upper())


class _FakeAuditLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def append_async(
        self,
        *,
        timestamp: str,
        conversation_id: str,
        event: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        self.calls.append(
            {
                "timestamp": timestamp,
                "conversation_id": conversation_id,
                "event": event,
                "metadata": metadata or {},
            }
        )


@pytest.mark.asyncio
async def test_tool_executor_allows_listed_tool(sample_agent_config: AgentConfig) -> None:
    fake_audit = _FakeAuditLogger()
    executor_module.get_audit_logger = lambda: fake_audit
    executor = ToolExecutor(sample_agent_config)
    result = await executor.try_execute(
        "search",
        _Params(query="hello"),
        _handler,
        context=AgentContext(thread_id="thread-allow"),
    )
    assert isinstance(result, _Result)
    assert result.value == "HELLO"
    assert fake_audit.calls[-1]["event"] == "tool_rbac_allowed"
    assert fake_audit.calls[-1]["conversation_id"] == "thread-allow"


@pytest.mark.asyncio
async def test_tool_executor_denies_unlisted_tool_structured(sample_agent_config: AgentConfig) -> None:
    fake_audit = _FakeAuditLogger()
    executor_module.get_audit_logger = lambda: fake_audit
    before = agent_metrics.rbac_denied_count(sample_agent_config.role, "send_email")
    executor = ToolExecutor(sample_agent_config)
    outcome = await executor.try_execute(
        "send_email",
        _Params(query="x"),
        _handler,
        context=AgentContext(thread_id="thread-deny"),
    )
    assert isinstance(outcome, ToolRbacDenied)
    assert outcome.tool_name == "send_email"
    assert outcome.allowed_tools == ("search",)
    assert fake_audit.calls[-1]["event"] == "permission_denied"
    assert fake_audit.calls[-1]["conversation_id"] == "thread-deny"
    assert agent_metrics.rbac_denied_count(sample_agent_config.role, "send_email") == before + 1


@pytest.mark.asyncio
async def test_tool_executor_execute_raises_for_legacy_callers(sample_agent_config: AgentConfig) -> None:
    fake_audit = _FakeAuditLogger()
    executor_module.get_audit_logger = lambda: fake_audit
    executor = ToolExecutor(sample_agent_config)
    with pytest.raises(ToolNotAllowedError) as exc_info:
        await executor.execute(
            "send_email",
            _Params(query="x"),
            _handler,
            context=AgentContext(thread_id="thread-deny"),
        )
    assert exc_info.value.tool_name == "send_email"
    assert exc_info.value.allowed_tools == ("search",)
