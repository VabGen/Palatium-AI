# src/palatium_ai/presentation/websockets/session.py

"""JWT-bound session websocket for turn/HITL push (HTTP fallback remains primary)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from palatium_ai.core.logging.context import trace_id_var, user_id_var
from palatium_ai.core.observability.trace_context import resolve_trace_id, trace_id_header_name
from palatium_ai.domain.sessions.ownership import evaluate_session_access
from palatium_ai.presentation.resources import get_app_resources
from palatium_ai.presentation.security.jwt import JwtTokenService, JwtValidationError
from palatium_ai.presentation.security.principal import AuthPrincipal

if TYPE_CHECKING:
    from fastapi import FastAPI

router = APIRouter()


@router.websocket("/sessions/{thread_id}")
async def session_events(websocket: WebSocket, thread_id: str) -> None:
    """Subscribe to session events after JWT + ownership checks."""
    await websocket.accept()
    trace_id = resolve_trace_id(header_value=websocket.headers.get(trace_id_header_name()))
    trace_token = trace_id_var.set(trace_id)
    user_token = user_id_var.set(None)
    try:
        principal = _authenticate_websocket(websocket)
        user_id_var.reset(user_token)
        user_token = user_id_var.set(principal.subject)

        resources = get_app_resources(websocket.app)
        session = await resources.session_service.get_session(thread_id=thread_id)
        decision = evaluate_session_access(
            owner_user_id=session.user_id if session is not None else None,
            caller_user_id=principal.subject,
            is_admin=principal.has_any_role(frozenset({"admin"})),
            allow_missing=session is None,
            session_exists=session is not None,
            allow_claim=False,
        )
        if not decision.allowed:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="session_access_denied")
            return

        await websocket.send_json(
            {
                "type": "session.subscribed",
                "thread_id": thread_id,
                "trace_id": trace_id,
            }
        )

        while True:
            message = await websocket.receive_text()
            if message.strip().lower() == "ping":
                await websocket.send_json({"type": "pong", "trace_id": trace_id})
                continue
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "detail": "invalid_json"})
                continue
            if payload.get("type") == "ping":
                await websocket.send_json({"type": "pong", "trace_id": trace_id})
    except WebSocketDisconnect:
        return
    except JwtValidationError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="unauthorized")
    finally:
        trace_id_var.reset(trace_token)
        user_id_var.reset(user_token)


def _authenticate_websocket(websocket: WebSocket) -> AuthPrincipal:
    security = websocket.app.state.security_config
    if not security.auth_enabled:
        return AuthPrincipal(subject="anonymous", roles=frozenset())

    token = websocket.query_params.get("token", "").strip()
    if not token:
        auth_header = websocket.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
    if not token:
        raise JwtValidationError("Missing bearer token")

    token_service: JwtTokenService = websocket.app.state.token_service
    return token_service.verify_bearer(token)


def register_websocket_routes(app: FastAPI) -> None:
    """Mount websocket routes under /ws."""
    app.include_router(router, prefix="/ws", tags=["websockets"])
