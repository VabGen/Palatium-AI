# tests/unit/test_tool_executor.py

"""Тесты RBAC ToolExecutor."""

from __future__ import annotations

import pytest

from pydantic import BaseModel

import palatium_ai.application.tools.executor as executor_module

from palatium_ai.application.tools.executor import ToolExecutor
from palatium_ai.core.exceptions import ToolNotAllowedError
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
    result = await executor.execute(
        "search",
        _Params(query="hello"),
        _handler,
        context=AgentContext(thread_id="thread-allow"),
    )
    assert result.value == "HELLO"
    assert fake_audit.calls[-1]["event"] == "tool_rbac_allowed"
    assert fake_audit.calls[-1]["conversation_id"] == "thread-allow"


@pytest.mark.asyncio
async def test_tool_executor_denies_unlisted_tool(sample_agent_config: AgentConfig) -> None:
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
    assert fake_audit.calls[-1]["event"] == "tool_rbac_denied"
    assert fake_audit.calls[-1]["conversation_id"] == "thread-deny"
