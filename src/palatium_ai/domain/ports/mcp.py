# src/palatium_ai/domain/ports/mcp.py

"""Порты доступа к MCP серверам и tools."""

from __future__ import annotations

from typing import Protocol

from palatium_ai.domain.mcp.models import (
    MCPToolCall,
    MCPToolDescriptor,
    MCPToolResult,
    MCPToolSummary,
)


class MCPClientPort(Protocol):
    """Контракт JSON-RPC взаимодействия с MCP server."""

    async def list_tools(self) -> list[MCPToolDescriptor]:
        """Получает список tools у MCP server."""
        ...

    async def list_tool_summaries(self) -> list[MCPToolSummary]:
        """Discovery cards without requiring full inputSchema on the wire."""
        ...

    async def call_tool(self, tool_call: MCPToolCall) -> MCPToolResult:
        """Вызывает tool на MCP server."""
        ...


class MCPRegistryPort(Protocol):
    """Контракт реестра MCP серверов и их capability discovery."""

    def list_servers(self) -> list[str]:
        """Возвращает имена зарегистрированных MCP servers."""
        ...

    async def list_tools(self, server_name: str) -> list[MCPToolDescriptor]:
        """Возвращает tools конкретного MCP server (full schemas)."""
        ...

    async def list_tool_summaries(self, server_name: str) -> list[MCPToolSummary]:
        """Progressive disclosure: discovery without full inputSchema in the hot path."""
        ...

    async def get_tool(self, server_name: str, tool_name: str) -> MCPToolDescriptor | None:
        """Load one tool descriptor (schema) when executing / building args."""
        ...

    async def call_tool(
        self,
        server_name: str,
        tool_call: MCPToolCall,
        *,
        allow_unpinned: bool = False,
    ) -> MCPToolResult:
        """Валидирует pin (Host) + schema и вызывает tool на выбранном сервере."""
        ...


class McpServerUnavailableError(RuntimeError):
    """A MCP server cannot serve calls right now (transport failure / open circuit).

    Part of the port contract, not an adapter detail: callers must be able to tell
    "the corporate search module is down" from "the tool ran and returned an error",
    because the two produce different user-facing answers (Level 5 graceful
    degradation, 035). Adapters raise a subclass; application code catches this base.
    """

    def __init__(
        self,
        server_name: str,
        *,
        retry_after_seconds: float | None = None,
        detail: str | None = None,
    ) -> None:
        self.server_name = server_name
        self.retry_after_seconds = retry_after_seconds
        message = detail or f"MCP server '{server_name}' is unavailable"
        super().__init__(message)


class McpToolCallRecorderPort(Protocol):
    """Контракт записи факта MCP tool call (audit/persistence), без ORM в application."""

    async def create_call(
        self,
        *,
        conversation_id: str,
        server_name: str,
        tool_name: str,
        arguments: dict[str, object],
        content: list[dict[str, object]],
        is_error: bool,
        event: str,
        user_id: str | None = None,
    ) -> object:
        """Persist or otherwise record one MCP tool invocation."""
        ...
