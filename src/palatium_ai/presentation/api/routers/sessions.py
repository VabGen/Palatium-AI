# src/palatium_ai/presentation/api/routers/sessions.py

"""API-роуты для сессий пользователя."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from palatium_ai.domain.mcp.api_redaction import redact_mcp_arguments, redact_mcp_content
from palatium_ai.presentation.resources import get_app_resources
from palatium_ai.presentation.security.deps import get_principal, principal_is_admin
from palatium_ai.presentation.security.ownership import load_session_for_principal

router = APIRouter()


class SessionResponse(BaseModel):
    """Public response model for a persisted session."""

    id: UUID
    thread_id: str
    user_id: str | None = None
    status: str
    title: str | None = None
    context: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    """Response envelope for a list of sessions."""

    items: list[SessionResponse]
    limit: int
    offset: int
    count: int


class UpsertSessionRequest(BaseModel):
    """Manual session create/update payload."""

    thread_id: str = Field(min_length=1, max_length=128)
    title: str | None = Field(default=None, max_length=255)
    status: str = Field(default="active", min_length=1, max_length=32)
    context: dict[str, Any] = Field(default_factory=dict)


class DialogTurnResponse(BaseModel):
    """One persisted dialog turn."""

    id: UUID | None = None
    thread_id: str
    role: str
    content: str
    payload: dict[str, Any] | None = None
    task_id: str | None = None
    seq: int
    created_at: datetime | None = None


class DialogTurnListResponse(BaseModel):
    """Envelope for dialog turns."""

    items: list[DialogTurnResponse]
    limit: int
    count: int


class McpToolCallResponse(BaseModel):
    """Public response model for persisted MCP tool calls."""

    id: UUID
    session_id: UUID | None = None
    conversation_id: str
    server_name: str
    tool_name: str
    arguments: dict[str, Any]
    content: list[dict[str, Any]]
    is_error: bool
    event: str
    user_id: str | None = None
    created_at: datetime
    updated_at: datetime


class McpToolCallListResponse(BaseModel):
    """Response envelope for MCP tool call collections."""

    items: list[McpToolCallResponse]
    limit: int
    offset: int
    count: int


class SessionTimelineResponse(BaseModel):
    """Combined operational trace for a session and its MCP tool calls."""

    session: SessionResponse
    mcp_tool_calls: list[McpToolCallResponse]


@router.get("/", response_model=SessionListResponse)
async def list_sessions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> SessionListResponse:
    """List sessions owned by the caller. Admin may list all tenants."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    scope_user_id: str | None = None if principal_is_admin(request, principal) else principal.subject
    sessions = await resources.session_service.list_sessions(
        limit=limit,
        offset=offset,
        user_id=scope_user_id,
    )
    return SessionListResponse(
        items=[_to_response(item) for item in sessions],
        limit=limit,
        offset=offset,
        count=len(sessions),
    )


@router.post("/", response_model=SessionResponse)
async def upsert_session(body: UpsertSessionRequest, request: Request) -> SessionResponse:
    """Создаёт или обновляет persisted session по `thread_id` (owner = JWT sub)."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    existing = await resources.session_service.get_session(thread_id=body.thread_id)
    if (
        existing is not None
        and existing.user_id not in (None, principal.subject)
        and not principal_is_admin(request, principal)
    ):
        raise HTTPException(status_code=403, detail="Not allowed to update this session")
    session = await resources.session_service.touch_session(
        thread_id=body.thread_id,
        user_id=principal.subject,
        title=body.title,
        context_patch=body.context,
        status=body.status,
    )
    return _to_response(session)


@router.get("/health")
async def sessions_health() -> dict[str, str]:
    """Health-check эндпоинт слоя сессий."""
    return {"status": "ok"}


@router.get("/{thread_id}", response_model=SessionResponse)
async def get_session(thread_id: str, request: Request) -> SessionResponse:
    """Возвращает persisted session по её `thread_id`."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    session = await load_session_for_principal(
        request=request,
        principal=principal,
        session_service=resources.session_service,
        thread_id=thread_id,
        allow_missing=False,
    )
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{thread_id}' not found")
    return _to_response(session)


@router.get("/{thread_id}/turns", response_model=DialogTurnListResponse)
async def list_dialog_turns(
    thread_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
) -> DialogTurnListResponse:
    """Возвращает последние реплики диалога (transcript)."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    session = await load_session_for_principal(
        request=request,
        principal=principal,
        session_service=resources.session_service,
        thread_id=thread_id,
        allow_missing=True,
    )
    if session is None:
        return DialogTurnListResponse(items=[], limit=limit, count=0)
    store = resources.dialog_turn_store
    if store is None:
        return DialogTurnListResponse(items=[], limit=limit, count=0)
    window = await store.list_recent_turns(thread_id=thread_id, limit=limit)
    return DialogTurnListResponse(
        items=[
            DialogTurnResponse(
                id=turn.id,
                thread_id=turn.thread_id,
                role=turn.role,
                content=turn.content,
                payload=turn.payload,
                task_id=turn.task_id,
                seq=turn.seq,
                created_at=turn.created_at,
            )
            for turn in window.turns
        ],
        limit=limit,
        count=len(window.turns),
    )


@router.get("/{thread_id}/mcp-tool-calls", response_model=McpToolCallListResponse)
async def list_mcp_tool_calls(
    thread_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    event: str | None = Query(default=None),
    is_error: bool | None = Query(default=None),
    server_name: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
) -> McpToolCallListResponse:
    """Возвращает MCP tool calls, относящиеся к указанной session/thread."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    session = await load_session_for_principal(
        request=request,
        principal=principal,
        session_service=resources.session_service,
        thread_id=thread_id,
        allow_missing=False,
    )
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{thread_id}' not found")

    tool_calls = await resources.mcp_tool_call_repository.list_by_thread_id(
        thread_id=thread_id,
        limit=limit,
        offset=offset,
        event=event,
        is_error=is_error,
        server_name=server_name,
        include_archived=include_archived,
    )
    return McpToolCallListResponse(
        items=[_to_tool_call_response(item) for item in tool_calls],
        limit=limit,
        offset=offset,
        count=len(tool_calls),
    )


@router.get("/{thread_id}/timeline", response_model=SessionTimelineResponse)
async def get_session_timeline(
    thread_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    event: str | None = Query(default=None),
    is_error: bool | None = Query(default=None),
    server_name: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
) -> SessionTimelineResponse:
    """Возвращает session вместе со связанными MCP tool calls как единый operational trace."""
    principal = get_principal(request)
    resources = get_app_resources(request.app)
    session = await load_session_for_principal(
        request=request,
        principal=principal,
        session_service=resources.session_service,
        thread_id=thread_id,
        allow_missing=False,
    )
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{thread_id}' not found")

    tool_calls = await resources.mcp_tool_call_repository.list_by_thread_id(
        thread_id=thread_id,
        limit=limit,
        offset=offset,
        event=event,
        is_error=is_error,
        server_name=server_name,
        include_archived=include_archived,
    )
    return SessionTimelineResponse(
        session=_to_response(session),
        mcp_tool_calls=[_to_tool_call_response(item) for item in tool_calls],
    )


def _to_response(session: Any) -> SessionResponse:
    """Convert ORM entity to API response."""
    return SessionResponse(
        id=session.id,
        thread_id=session.thread_id,
        user_id=session.user_id,
        status=session.status,
        title=session.title,
        context=session.context,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _to_tool_call_response(tool_call: Any) -> McpToolCallResponse:
    """Convert ORM entity to API response (redacted args/content)."""
    raw_args = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
    raw_content = tool_call.content if isinstance(tool_call.content, list) else []
    return McpToolCallResponse(
        id=tool_call.id,
        session_id=tool_call.session_id,
        conversation_id=tool_call.conversation_id,
        server_name=tool_call.server_name,
        tool_name=tool_call.tool_name,
        arguments=redact_mcp_arguments(raw_args),
        content=redact_mcp_content(raw_content),
        is_error=tool_call.is_error,
        event=tool_call.event,
        user_id=tool_call.user_id,
        created_at=tool_call.created_at,
        updated_at=tool_call.updated_at,
    )
