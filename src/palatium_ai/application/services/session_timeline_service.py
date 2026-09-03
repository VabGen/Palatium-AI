# src/palatium_ai/application/services/session_timeline_service.py

"""Session operational trace assembly (turns + MCP tool calls)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue

from palatium_ai.domain.mcp.api_redaction import redact_mcp_arguments, redact_mcp_content
from palatium_ai.domain.memory.turns import DialogTurn

if TYPE_CHECKING:
    from palatium_ai.domain.memory.ports import DialogTurnStore
    from palatium_ai.infrastructure.database.repositories import McpToolCallRepository


class DialogTurnView(BaseModel):
    """Public dialog turn for API responses."""

    model_config = {"frozen": True}

    id: UUID | None = None
    thread_id: str
    role: str
    content: str
    payload: dict[str, JsonValue] | None = None
    task_id: str | None = None
    seq: int
    created_at: datetime | None = None


class McpToolCallView(BaseModel):
    """Redacted MCP tool call for API responses."""

    model_config = {"frozen": True}

    id: UUID
    session_id: UUID | None = None
    conversation_id: str
    server_name: str
    tool_name: str
    arguments: dict[str, JsonValue]
    content: list[dict[str, JsonValue]]
    is_error: bool
    event: str
    user_id: str | None = None
    created_at: datetime
    updated_at: datetime


class SessionTimelineView(BaseModel):
    """Combined session trace."""

    model_config = {"frozen": True}

    mcp_tool_calls: tuple[McpToolCallView, ...] = Field(default_factory=tuple)


class SessionTimelineService:
    """Load dialog turns and MCP tool calls for owned sessions."""

    def __init__(
        self,
        *,
        dialog_turn_store: DialogTurnStore | None,
        mcp_tool_call_repository: McpToolCallRepository,
    ) -> None:
        self._dialog_turn_store = dialog_turn_store
        self._mcp_tool_call_repository = mcp_tool_call_repository

    async def list_dialog_turns(self, *, thread_id: str, limit: int) -> list[DialogTurnView]:
        """Return recent dialog turns for a thread."""
        if self._dialog_turn_store is None:
            return []
        window = await self._dialog_turn_store.list_recent_turns(thread_id=thread_id, limit=limit)
        return [_turn_to_view(turn) for turn in window.turns]

    async def list_mcp_tool_calls(
        self,
        *,
        thread_id: str,
        limit: int,
        offset: int,
        event: str | None = None,
        is_error: bool | None = None,
        server_name: str | None = None,
        include_archived: bool = False,
    ) -> list[McpToolCallView]:
        """Return redacted MCP tool calls for a thread."""
        rows = await self._mcp_tool_call_repository.list_by_thread_id(
            thread_id=thread_id,
            limit=limit,
            offset=offset,
            event=event,
            is_error=is_error,
            server_name=server_name,
            include_archived=include_archived,
        )
        return [_tool_call_to_view(row) for row in rows]

    async def load_timeline(
        self,
        *,
        thread_id: str,
        limit: int,
        offset: int,
        event: str | None = None,
        is_error: bool | None = None,
        server_name: str | None = None,
        include_archived: bool = False,
    ) -> SessionTimelineView:
        """Load MCP tool calls for combined timeline endpoint."""
        calls = await self.list_mcp_tool_calls(
            thread_id=thread_id,
            limit=limit,
            offset=offset,
            event=event,
            is_error=is_error,
            server_name=server_name,
            include_archived=include_archived,
        )
        return SessionTimelineView(mcp_tool_calls=tuple(calls))


def _turn_to_view(turn: DialogTurn) -> DialogTurnView:
    return DialogTurnView(
        id=turn.id,
        thread_id=turn.thread_id,
        role=turn.role,
        content=turn.content,
        payload=turn.payload,
        task_id=turn.task_id,
        seq=turn.seq,
        created_at=turn.created_at,
    )


def _tool_call_to_view(tool_call: Any) -> McpToolCallView:
    raw_args = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
    raw_content = tool_call.content if isinstance(tool_call.content, list) else []
    return McpToolCallView(
        id=tool_call.id,
        session_id=tool_call.session_id,
        conversation_id=tool_call.conversation_id,
        server_name=tool_call.server_name,
        tool_name=tool_call.tool_name,
        arguments=cast("dict[str, JsonValue]", redact_mcp_arguments(raw_args)),
        content=cast("list[dict[str, JsonValue]]", redact_mcp_content(raw_content)),
        is_error=tool_call.is_error,
        event=tool_call.event,
        user_id=tool_call.user_id,
        created_at=tool_call.created_at,
        updated_at=tool_call.updated_at,
    )
