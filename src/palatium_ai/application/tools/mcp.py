# src/palatium_ai/application/tools/mcp.py

"""Typed wrapper for MCP tool execution."""

from __future__ import annotations

import json

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.domain.mcp.models import MCPToolCall, MCPToolResult
from palatium_ai.domain.policies.memory_namespace import MemoryNamespacePolicy

if TYPE_CHECKING:
    from palatium_ai.domain.ports.mcp import MCPRegistryPort, McpToolCallRecorderPort


class MCPToolCallParams(BaseModel):
    """Параметры вызова MCP tool."""

    model_config = {"frozen": True}

    server_name: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, object] = Field(default_factory=dict)
    # Trusted caller identity (JWT / ConsolidationJob) — never taken from tool args.
    actor_user_id: str = Field(default="", max_length=128)
    actor_org_id: str = Field(default="", max_length=128)
    actor_thread_id: str = Field(default="", max_length=128)


class MCPToolCallOutcome(BaseModel):
    """Типизированный результат вызова MCP tool."""

    model_config = {"frozen": True}

    content: list[dict[str, object]] = Field(default_factory=list)
    is_error: bool = False


def _bind_arguments(params: MCPToolCallParams) -> dict[str, object]:
    """Apply actor binding for platform tenant tools; other tools pass through."""
    if params.server_name != "platform":
        return dict(params.arguments)
    return MemoryNamespacePolicy.bind_mcp_memory_arguments(
        tool_name=params.tool_name,
        arguments=params.arguments,
        actor_user_id=params.actor_user_id,
        actor_org_id=params.actor_org_id,
        actor_thread_id=params.actor_thread_id,
    )


async def call_mcp_tool(
    params: MCPToolCallParams,
    registry: MCPRegistryPort,
    *,
    conversation_id: str | None = None,
    repository: McpToolCallRecorderPort | None = None,
) -> MCPToolCallOutcome:
    """Вызывает MCP tool через registry с JSON Schema validation."""
    try:
        arguments = _bind_arguments(params)
    except ValueError as exc:
        return MCPToolCallOutcome(
            content=[{"type": "text", "text": json.dumps({"error": str(exc)}, ensure_ascii=False)}],
            is_error=True,
        )

    result: MCPToolResult = await registry.call_tool(
        params.server_name,
        MCPToolCall(
            name=params.tool_name,
            arguments=arguments,
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
            arguments=arguments,
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
