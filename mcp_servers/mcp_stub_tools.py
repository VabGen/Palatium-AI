# mcp_servers/mcp_stub_tools.py

"""Shared helpers for MCP stub tools/list progressive disclosure."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def tools_list_payload(
    tools: Sequence[Mapping[str, object]],
    params: Mapping[str, object] | None,
) -> list[dict[str, object]]:
    """Return tools for tools/list; omit inputSchema when client asks.

    Palatium extension (stubs): ``omitInputSchema: true`` returns discovery cards
    with ``propertyNames`` instead of full JSON Schema. Unknown servers ignore the
    flag; the platform client falls back to stripping locally.
    """
    omit = bool((params or {}).get("omitInputSchema"))
    if not omit:
        return [dict(tool) for tool in tools]

    slim: list[dict[str, object]] = []
    for tool in tools:
        card = {key: value for key, value in tool.items() if key != "inputSchema"}
        schema = tool.get("inputSchema")
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if isinstance(properties, dict):
            card["propertyNames"] = [str(name) for name in properties]
        slim.append(card)
    return slim
