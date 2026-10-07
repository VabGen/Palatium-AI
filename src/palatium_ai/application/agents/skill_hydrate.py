# src/palatium_ai/application/agents/skill_hydrate.py

"""Load matching procedural skill references via MCP (progressive disclosure L2/L3)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING

from palatium_ai.application.tools.executor import ToolExecutor, ToolRbacDenied
from palatium_ai.application.tools.mcp import MCPToolCallOutcome, MCPToolCallParams, call_mcp_tool
from palatium_ai.core.logging import get_logger
from palatium_ai.domain.agents.contracts import AgentContext
from palatium_ai.domain.skills.select import parse_skill_catalog_entries, select_skills_by_overlap

if TYPE_CHECKING:
    from palatium_ai.domain.ports.mcp import MCPRegistryPort, McpToolCallRecorderPort

logger = get_logger(__name__)

_MAX_SKILLS = 2
_MAX_CHARS_PER_SKILL = 4_000


async def hydrate_skill_references(
    *,
    catalog_text: str,
    user_text: str,
    tool_executor: ToolExecutor,
    mcp_registry: MCPRegistryPort | None,
    context: AgentContext,
    repository: McpToolCallRecorderPort | None = None,
) -> str:
    """Select overlapping skills from level-1 catalog and load bodies via ``skill_reference``."""
    if mcp_registry is None or not catalog_text.strip():
        return ""
    if catalog_text.strip() == "(no procedural skills)":
        return ""
    names = select_skills_by_overlap(
        user_text,
        parse_skill_catalog_entries(catalog_text),
        limit=_MAX_SKILLS,
    )
    if not names:
        return ""
    chunks: list[str] = []
    for name in names:
        text = await _fetch_one(
            name=name,
            tool_executor=tool_executor,
            mcp_registry=mcp_registry,
            context=context,
            repository=repository,
        )
        if text:
            chunks.append(f"### skill:{name}\n{text}")
    return "\n\n".join(chunks)


async def _fetch_one(
    *,
    name: str,
    tool_executor: ToolExecutor,
    mcp_registry: MCPRegistryPort,
    context: AgentContext,
    repository: McpToolCallRecorderPort | None,
) -> str:
    params = MCPToolCallParams(
        server_name="platform",
        tool_name="skill_reference",
        arguments={"name": name},
        actor_user_id=(context.user_id or "").strip(),
        actor_org_id=(context.org_id or "").strip(),
        actor_thread_id=context.thread_id,
    )

    async def _handle(payload: MCPToolCallParams) -> MCPToolCallOutcome:
        return await call_mcp_tool(
            payload,
            mcp_registry,
            conversation_id=context.thread_id,
            repository=repository,
        )

    outcome = await tool_executor.try_execute(
        "mcp.call",
        params,
        _handle,
        context=context,
    )
    if isinstance(outcome, ToolRbacDenied):
        logger.warning("skill_hydrate.rbac_denied", skill=name, message=outcome.message)
        return ""
    if outcome.is_error:
        return ""
    return _content_from_outcome(outcome, skill_name=name)


def _content_from_outcome(outcome: MCPToolCallOutcome, *, skill_name: str) -> str:
    if not outcome.content:
        return ""
    raw = outcome.content[0].get("text")
    if not isinstance(raw, str) or not raw.strip():
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:_MAX_CHARS_PER_SKILL]
    if not isinstance(payload, dict):
        return raw[:_MAX_CHARS_PER_SKILL]
    if payload.get("error"):
        logger.warning("skill_hydrate.tool_error", skill=skill_name, error=payload.get("error"))
        return ""
    body = payload.get("content")
    if not isinstance(body, str):
        return ""
    return body[:_MAX_CHARS_PER_SKILL]
