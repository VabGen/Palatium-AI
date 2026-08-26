# src/palatium_ai/application/services/session_service.py

"""Application service for session lifecycle persistence."""

from __future__ import annotations

from typing import Any

from palatium_ai.core.exceptions import SessionOwnershipError
from palatium_ai.domain.sessions.ownership import evaluate_session_access
from palatium_ai.infrastructure.database.models import SessionORM
from palatium_ai.infrastructure.database.repositories import SessionRepository


class SessionService:
    """High-level use cases for persistent conversation sessions."""

    def __init__(self, repository: SessionRepository) -> None:
        self._repository = repository

    async def assert_thread_access(
        self,
        *,
        thread_id: str,
        user_id: str | None,
        is_admin: bool = False,
        allow_missing: bool = True,
    ) -> SessionORM | None:
        """Fail closed when the caller does not own an existing thread."""
        session = await self._repository.get_by_thread_id(thread_id=thread_id)
        decision = evaluate_session_access(
            owner_user_id=getattr(session, "user_id", None) if session is not None else None,
            caller_user_id=user_id,
            is_admin=is_admin,
            allow_missing=allow_missing,
            session_exists=session is not None,
            allow_claim=True,
        )
        if not decision.allowed:
            raise SessionOwnershipError(
                "Not allowed to access this session",
            )
        return session

    async def touch_session(
        self,
        *,
        thread_id: str,
        user_id: str | None = None,
        title: str | None = None,
        context_patch: dict[str, Any] | None = None,
        status: str = "active",
    ) -> SessionORM:
        """Create or update a session based on the incoming conversation context."""
        return await self._repository.touch_session(
            thread_id=thread_id,
            user_id=user_id,
            title=title,
            context_patch=context_patch,
            status=status,
        )

    async def list_sessions(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        user_id: str | None = None,
    ) -> list[SessionORM]:
        """Return recently updated sessions (optionally scoped to one user)."""
        return await self._repository.list_sessions(limit=limit, offset=offset, user_id=user_id)

    async def get_session(self, *, thread_id: str) -> SessionORM | None:
        """Return a single session by its stable thread ID."""
        return await self._repository.get_by_thread_id(thread_id=thread_id)
