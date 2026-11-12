# src/palatium_ai/domain/projects/ports.py

"""Project persistence port (DIP)."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from palatium_ai.domain.projects.models import ProjectRecord


class ProjectStore(Protocol):
    """Abstract persistence for first-class projects."""

    async def create(self, *, user_id: str, title: str) -> ProjectRecord:
        """Insert a new project owned by ``user_id``."""
        ...

    async def list_for_user(
        self,
        *,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ProjectRecord]:
        """Return projects for one owner, newest first."""
        ...

    async def get_for_user(self, *, user_id: str, project_id: UUID) -> ProjectRecord | None:
        """Fetch one project if owned by ``user_id``."""
        ...

    async def rename(
        self,
        *,
        user_id: str,
        project_id: UUID,
        title: str,
    ) -> ProjectRecord | None:
        """Update title; ``None`` when missing or not owned."""
        ...

    async def delete(self, *, user_id: str, project_id: UUID) -> bool:
        """Delete owned project; ``False`` when missing or not owned."""
        ...
