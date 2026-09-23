# mcp_servers/gateway/pin_filter.py

"""FastMCP middleware: expose only platform-pinned tool names from upstream."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware


class PinAllowlistMiddleware(Middleware):
    """Drop unpinned tools from list/call; Host ToolPolicy remains authoritative."""

    def __init__(self, allowed_tool_names: Collection[str]) -> None:
        self._allowed = frozenset(allowed_tool_names)

    async def on_list_tools(self, context: Any, call_next: Any) -> Any:
        result = await call_next(context)
        return _filter_tool_list(result, self._allowed)

    async def on_call_tool(self, context: Any, call_next: Any) -> Any:
        name = _tool_name_from_context(context)
        if name is None or name not in self._allowed:
            raise ToolError(f"Tool {name!r} is not in the platform pin allowlist; refusing gateway tools/call")
        return await call_next(context)

    async def on_list_resources(self, context: Any, call_next: Any) -> Any:
        _ = (context, call_next)
        return []

    async def on_list_prompts(self, context: Any, call_next: Any) -> Any:
        _ = (context, call_next)
        return []

    async def on_list_resource_templates(self, context: Any, call_next: Any) -> Any:
        _ = (context, call_next)
        return []


def _tool_name_from_context(context: Any) -> str | None:
    message = getattr(context, "message", None)
    if message is None:
        return None
    name = getattr(message, "name", None)
    if isinstance(name, str) and name:
        return name
    params = getattr(message, "params", None)
    pname = getattr(params, "name", None) if params is not None else None
    return pname if isinstance(pname, str) and pname else None


def _filter_tool_list(result: Any, allowed: frozenset[str]) -> Any:
    if result is None:
        return result
    if hasattr(result, "tools"):
        tools = [tool for tool in result.tools if getattr(tool, "name", None) in allowed]
        if hasattr(result, "model_copy"):
            return result.model_copy(update={"tools": tools})
        try:
            return type(result)(tools=tools)
        except TypeError:
            return tools
    if isinstance(result, list):
        return [tool for tool in result if getattr(tool, "name", None) in allowed]
    return result
