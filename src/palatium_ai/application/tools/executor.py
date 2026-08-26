# src/palatium_ai/application/tools/executor.py

"""RBAC-исполнитель инструментов агента."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypeVar

import structlog

from palatium_ai.application.tools.mcp import MCPToolCallParams
from palatium_ai.core.exceptions import ToolNotAllowedError
from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.mcp.tool_policy import is_tool_invocation_allowed

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pydantic import BaseModel

    from palatium_ai.domain.agents.agent_config import AgentConfig
    from palatium_ai.domain.agents.contracts import AgentContext

logger = structlog.get_logger(__name__)

P = TypeVar("P", bound="BaseModel")
R = TypeVar("R", bound="BaseModel")


class ToolExecutor:
    """Проверяет RBAC allow-list до вызова инструмента."""

    def __init__(self, agent_config: AgentConfig) -> None:
        self._config = agent_config
        self._allowed = frozenset(agent_config.allowed_tools)

    @traceable(name="tool_executor.execute")
    async def execute(
        self,
        tool_name: str,
        params: P,
        handler: Callable[[P], Awaitable[R]],
        context: AgentContext | None = None,
    ) -> R:
        """Вызывает handler только если tool_name ∈ allowed_tools (MCP — per-tool)."""
        conversation_id = context.thread_id if context is not None else self._config.name
        server_name, mcp_tool_name = _mcp_identity(params)
        if not is_tool_invocation_allowed(
            self._allowed,
            tool_name=tool_name,
            server_name=server_name,
            mcp_tool_name=mcp_tool_name,
        ):
            logger.warning(
                "tool.rbac.denied",
                tool_name=tool_name,
                server_name=server_name,
                mcp_tool_name=mcp_tool_name,
                agent=self._config.name,
                allowed_tools=sorted(self._allowed),
            )
            await _write_audit_event(
                conversation_id=conversation_id,
                event="tool_rbac_denied",
                metadata={
                    "agent": self._config.name,
                    "tool_name": tool_name,
                    "server_name": server_name or "",
                    "mcp_tool_name": mcp_tool_name or "",
                },
            )
            raise ToolNotAllowedError(tool_name, self._config.allowed_tools)

        logger.debug(
            "tool.rbac.allowed",
            tool_name=tool_name,
            server_name=server_name,
            mcp_tool_name=mcp_tool_name,
            agent=self._config.name,
        )
        await _write_audit_event(
            conversation_id=conversation_id,
            event="tool_rbac_allowed",
            metadata={
                "agent": self._config.name,
                "tool_name": tool_name,
                "server_name": server_name or "",
                "mcp_tool_name": mcp_tool_name or "",
            },
        )
        return await handler(params)


def _mcp_identity(params: BaseModel) -> tuple[str | None, str | None]:
    if isinstance(params, MCPToolCallParams):
        return params.server_name, params.tool_name
    return None, None


async def _write_audit_event(
    *,
    conversation_id: str,
    event: str,
    metadata: dict[str, str],
) -> None:
    """Пишет tamper-evident audit event для RBAC-решений."""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    await get_audit_logger().append_async(
        timestamp=timestamp,
        conversation_id=conversation_id,
        event=event,
        metadata=metadata,
    )
