# src/palatium_ai/domain/sessions/ports.py

"""Session persistence port (DIP)."""

from __future__ import annotations

from typing import Protocol

from palatium_ai.domain.sessions.models import SessionRecord


class SessionStore(Protocol):
    """Abstract persistence for conversation sessions."""

    async def get_by_thread_id(self, *, thread_id: str) -> SessionRecord | None:
        """Find a session by its stable thread identifier."""
        ...

    async def touch_session(
        self,
        *,
        thread_id: str,
        user_id: str | None = None,
        title: str | None = None,
        context_patch: dict[str, object] | None = None,
        status: str = "active",
    ) -> SessionRecord:
        """Create or update a session identified by `thread_id`."""
        ...

    async def list_sessions(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> list[SessionRecord]:
        """Return recently updated sessions (optionally scoped to user/project)."""
        ...

    async def set_project_id(
        self,
        *,
        thread_id: str,
        project_id: str | None,
    ) -> SessionRecord:
        """Pin or unpin a session to a project id string."""
        ...

    async def set_title(
        self,
        *,
        thread_id: str,
        title: str,
    ) -> SessionRecord:
        """Overwrite the session title (user rename)."""
        ...

    async def set_status(
        self,
        *,
        thread_id: str,
        status: str,
    ) -> SessionRecord:
        """Update lifecycle status (e.g. ``active`` → ``archived``)."""
        ...
