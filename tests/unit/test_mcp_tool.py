# tests/unit/test_mcp_tool.py

"""Тесты audit-aware MCP tool wrapper."""

from __future__ import annotations

import pytest

import palatium_ai.application.tools.mcp as mcp_module

from palatium_ai.application.tools.mcp import MCPToolCallParams, call_mcp_tool
from palatium_ai.domain.mcp.models import MCPToolCall, MCPToolResult
from tests.conftest import FakeMCPRegistry


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
async def test_call_mcp_tool_writes_audit_event() -> None:
    fake_audit = _FakeAuditLogger()
    mcp_module.get_audit_logger = lambda: fake_audit
    registry = FakeMCPRegistry()

    result = await call_mcp_tool(
        MCPToolCallParams(
            server_name="edms",
            tool_name="search_documents",
            arguments={"query": "Find the contract in EDMS"},
        ),
        registry,
        conversation_id="thread-mcp-1",
    )

    assert result.is_error is False
    assert fake_audit.calls[-1]["event"] == "mcp_tool_succeeded"
    assert fake_audit.calls[-1]["conversation_id"] == "thread-mcp-1"
    assert fake_audit.calls[-1]["metadata"]["tool_name"] == "search_documents"


class _FakeErrorMCPRegistry(FakeMCPRegistry):
    async def call_tool(self, server_name: str, tool_call: MCPToolCall) -> MCPToolResult:
        self.calls.append((server_name, tool_call))
        return MCPToolResult(
            content=[],
            isError=True,
        )


@pytest.mark.asyncio
async def test_call_mcp_tool_writes_audit_event_on_failure() -> None:
    fake_audit = _FakeAuditLogger()
    mcp_module.get_audit_logger = lambda: fake_audit
    registry = _FakeErrorMCPRegistry()

    result = await call_mcp_tool(
        MCPToolCallParams(
            server_name="edms",
            tool_name="search_documents",
            arguments={"query": "Find the contract in EDMS"},
        ),
        registry,
        conversation_id="thread-mcp-err-1",
    )

    assert result.is_error is True
    assert fake_audit.calls[-1]["event"] == "mcp_tool_failed"
    assert fake_audit.calls[-1]["conversation_id"] == "thread-mcp-err-1"
