# src/palatium_ai/presentation/api/routers/sessions.py

"""API-роуты для сессий пользователя."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, JsonValue

from palatium_ai.domain.sessions.context_privacy import (
    filter_client_context_patch,
    public_session_context,
)
from palatium_ai.domain.sessions.models import SessionRecord
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
    context: dict[str, JsonValue]
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
    context: dict[str, JsonValue] = Field(default_factory=dict)


class DialogTurnResponse(BaseModel):
    """One persisted dialog turn."""

    id: UUID | None = None
    thread_id: str
    role: str
    content: str
    payload: dict[str, JsonValue] | None = None
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
    arguments: dict[str, JsonValue]
    content: list[dict[str, JsonValue]]
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
    if existing is not None and not principal_is_admin(request, principal) and existing.user_id != principal.subject:
        # Exact owner match only — unowned residual sessions are not claimable (IDOR).
        raise HTTPException(status_code=403, detail="Not allowed to update this session")
    session = await resources.session_service.touch_session(
        thread_id=body.thread_id,
        user_id=principal.subject,
        title=body.title,
        # Control-plane keys (HITL counters, critic, effective text) are server-only.
        context_patch=filter_client_context_patch(body.context),
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
    timeline = resources.session_timeline_service
    if timeline is None:
        return DialogTurnListResponse(items=[], limit=limit, count=0)
    turns = await timeline.list_dialog_turns(thread_id=thread_id, limit=limit)
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
            for turn in turns
        ],
        limit=limit,
        count=len(turns),
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

    timeline = resources.session_timeline_service
    if timeline is None:
        return McpToolCallListResponse(items=[], limit=limit, offset=offset, count=0)
    tool_calls = await timeline.list_mcp_tool_calls(
        thread_id=thread_id,
        limit=limit,
        offset=offset,
        event=event,
        is_error=is_error,
        server_name=server_name,
        include_archived=include_archived,
    )
    return McpToolCallListResponse(
        items=[
            McpToolCallResponse(
                id=item.id,
                session_id=item.session_id,
                conversation_id=item.conversation_id,
                server_name=item.server_name,
                tool_name=item.tool_name,
                arguments=item.arguments,
                content=item.content,
                is_error=item.is_error,
                event=item.event,
                user_id=item.user_id,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in tool_calls
        ],
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

    timeline = resources.session_timeline_service
    if timeline is None:
        return SessionTimelineResponse(session=_to_response(session), mcp_tool_calls=[])
    view = await timeline.load_timeline(
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
        mcp_tool_calls=[
            McpToolCallResponse(
                id=item.id,
                session_id=item.session_id,
                conversation_id=item.conversation_id,
                server_name=item.server_name,
                tool_name=item.tool_name,
                arguments=item.arguments,
                content=item.content,
                is_error=item.is_error,
                event=item.event,
                user_id=item.user_id,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in view.mcp_tool_calls
        ],
    )


def _to_response(session: SessionRecord) -> SessionResponse:
    """Convert domain session record to API response."""
    return SessionResponse(
        id=session.id,
        thread_id=session.thread_id,
        user_id=session.user_id,
        status=session.status,
        title=session.title,
        context=cast("dict[str, JsonValue]", public_session_context(session.context)),
        created_at=session.created_at,
        updated_at=session.updated_at,
    )
