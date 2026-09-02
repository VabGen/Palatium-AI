# src/palatium_ai/application/services/session_service.py

"""Application service for session lifecycle persistence."""

from __future__ import annotations

from palatium_ai.domain.sessions.errors import SessionOwnershipError
from palatium_ai.domain.sessions.models import SessionRecord
from palatium_ai.domain.sessions.ownership import evaluate_session_access
from palatium_ai.domain.sessions.ports import SessionStore


class SessionService:
    """High-level use cases for persistent conversation sessions."""

    def __init__(self, store: SessionStore) -> None:
        self._store = store

    async def assert_thread_access(
        self,
        *,
        thread_id: str,
        user_id: str | None,
        is_admin: bool = False,
        allow_missing: bool = True,
    ) -> SessionRecord | None:
        """Fail closed when the caller does not own an existing thread."""
        session = await self._store.get_by_thread_id(thread_id=thread_id)
        decision = evaluate_session_access(
            owner_user_id=session.user_id if session is not None else None,
            caller_user_id=user_id,
            is_admin=is_admin,
            allow_missing=allow_missing,
            session_exists=session is not None,
            # Existing unowned threads are admin-only (no stranger claim / residual IDOR).
            allow_claim=False,
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
        context_patch: dict[str, object] | None = None,
        status: str = "active",
    ) -> SessionRecord:
        """Create or update a session based on the incoming conversation context."""
        return await self._store.touch_session(
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
    ) -> list[SessionRecord]:
        """Return recently updated sessions (optionally scoped to one user)."""
        return await self._store.list_sessions(limit=limit, offset=offset, user_id=user_id)

    async def get_session(self, *, thread_id: str) -> SessionRecord | None:
        """Return a single session by its stable thread ID."""
        return await self._store.get_by_thread_id(thread_id=thread_id)
