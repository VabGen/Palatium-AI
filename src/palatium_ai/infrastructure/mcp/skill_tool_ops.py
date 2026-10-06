# src/palatium_ai/infrastructure/mcp/skill_tool_ops.py

"""In-process ``skill_reference`` MCP op (070 / Wave M6)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING

from palatium_ai.domain.mcp.models import MCPToolResult

if TYPE_CHECKING:
    from palatium_ai.domain.skills.port import SkillCatalogPort


async def skill_reference(
    catalog: SkillCatalogPort | None,
    arguments: dict[str, object],
) -> MCPToolResult:
    if catalog is None:
        return _error_result("skill_reference unavailable: skill catalog not configured")
    name = arguments.get("name")
    if not isinstance(name, str) or not name.strip():
        return _error_result("Invalid params: name is required")
    doc = catalog.get_reference(name.strip())
    if doc is None:
        return _error_result(f"Unknown skill: {name.strip()}")
    payload = {
        "tool": "skill_reference",
        "name": doc.name,
        "kind": doc.kind,
        "truncated": doc.truncated,
        "content": doc.content,
    }
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        is_error=False,
    )


def _error_result(message: str) -> MCPToolResult:
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps({"error": message}, ensure_ascii=False)}],
        is_error=True,
    )
