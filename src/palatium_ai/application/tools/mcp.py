# src/palatium_ai/application/tools/mcp.py

"""Typed wrapper for MCP tool execution."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.domain.mcp.models import MCPToolCall, MCPToolResult

if TYPE_CHECKING:
    from palatium_ai.domain.ports.mcp import MCPRegistryPort, McpToolCallRecorderPort


class MCPToolCallParams(BaseModel):
    """Параметры вызова MCP tool."""

    model_config = {"frozen": True}

    server_name: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, object] = Field(default_factory=dict)


class MCPToolCallOutcome(BaseModel):
    """Типизированный результат вызова MCP tool."""

    model_config = {"frozen": True}

    content: list[dict[str, object]] = Field(default_factory=list)
    is_error: bool = False


async def call_mcp_tool(
    params: MCPToolCallParams,
    registry: MCPRegistryPort,
    *,
    conversation_id: str | None = None,
    repository: McpToolCallRecorderPort | None = None,
) -> MCPToolCallOutcome:
    """Вызывает MCP tool через registry с JSON Schema validation."""
    result: MCPToolResult = await registry.call_tool(
        params.server_name,
        MCPToolCall(
            name=params.tool_name,
            arguments=params.arguments,
        ),
    )
    event = "mcp_tool_failed" if result.is_error else "mcp_tool_succeeded"
    await _write_mcp_audit_event(
        conversation_id=conversation_id or f"{params.server_name}.{params.tool_name}",
        event=event,
        metadata={
            "server_name": params.server_name,
            "tool_name": params.tool_name,
            "is_error": str(result.is_error),
        },
    )
    if repository is not None:
        await repository.create_call(
            conversation_id=conversation_id or f"{params.server_name}.{params.tool_name}",
            server_name=params.server_name,
            tool_name=params.tool_name,
            arguments=params.arguments,
            content=result.content,
            is_error=result.is_error,
            event=event,
        )
    return MCPToolCallOutcome(content=result.content, is_error=result.is_error)


async def _write_mcp_audit_event(
    *,
    conversation_id: str,
    event: str,
    metadata: dict[str, str],
) -> None:
    """Пишет audit-событие по факту MCP tool call."""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    await get_audit_logger().append_async(
        timestamp=timestamp,
        conversation_id=conversation_id,
        event=event,
        metadata=metadata,
    )
