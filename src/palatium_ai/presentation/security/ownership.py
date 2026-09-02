# src/palatium_ai/presentation/security/ownership.py

"""Session / HITL ownership checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, status

from palatium_ai.domain.sessions.models import SessionRecord
from palatium_ai.domain.sessions.ownership import evaluate_session_access
from palatium_ai.presentation.security.deps import principal_is_admin
from palatium_ai.presentation.security.principal import AuthPrincipal

if TYPE_CHECKING:
    from fastapi import Request

    from palatium_ai.application.services.session_service import SessionService


def assert_session_access(
    *,
    request: Request,
    principal: AuthPrincipal,
    session: SessionRecord | None,
    allow_missing: bool = False,
    allow_claim: bool = False,
) -> SessionRecord | None:
    """Enforce that the principal owns the session (or is admin).

    Missing sessions are allowed when `allow_missing` is True (fresh thread before first turn).
    Unowned (`user_id is None`) sessions are admin-only — never claimable by strangers.
    """
    decision = evaluate_session_access(
        owner_user_id=session.user_id if session is not None else None,
        caller_user_id=principal.subject,
        is_admin=principal_is_admin(request, principal),
        allow_missing=allow_missing,
        session_exists=session is not None,
        allow_claim=allow_claim,
    )
    if decision.allowed:
        return session
    if decision.reason == "session_not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not allowed to access this session",
    )


async def load_session_for_principal(
    *,
    request: Request,
    principal: AuthPrincipal,
    session_service: SessionService,
    thread_id: str,
    allow_missing: bool = False,
    allow_claim: bool = False,
) -> SessionRecord | None:
    """Fetch session and apply ownership gate (read-safe by default)."""
    session = await session_service.get_session(thread_id=thread_id)
    return assert_session_access(
        request=request,
        principal=principal,
        session=session,
        allow_missing=allow_missing,
        allow_claim=allow_claim,
    )
