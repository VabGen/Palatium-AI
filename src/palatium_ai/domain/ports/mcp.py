# src/palatium_ai/domain/ports/mcp.py

"""Порты доступа к MCP серверам и tools."""

from __future__ import annotations

from typing import Protocol

from palatium_ai.domain.mcp.models import MCPToolCall, MCPToolDescriptor, MCPToolResult


class MCPClientPort(Protocol):
    """Контракт JSON-RPC взаимодействия с MCP server."""

    async def list_tools(self) -> list[MCPToolDescriptor]:
        """Получает список tools у MCP server."""
        ...

    async def call_tool(self, tool_call: MCPToolCall) -> MCPToolResult:
        """Вызывает tool на MCP server."""
        ...


class MCPRegistryPort(Protocol):
    """Контракт реестра MCP серверов и их capability discovery."""

    async def list_tools(self, server_name: str) -> list[MCPToolDescriptor]:
        """Возвращает tools конкретного MCP server."""
        ...

    async def call_tool(self, server_name: str, tool_call: MCPToolCall) -> MCPToolResult:
        """Валидирует и вызывает tool на выбранном сервере."""
        ...
