# src/palatium_ai/application/services/project_service.py

"""Use cases for durable Projects (create / list / rename / pin validation)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.domain.projects.errors import ProjectNotFoundError
from palatium_ai.domain.projects.models import ProjectRecord

if TYPE_CHECKING:
    from palatium_ai.application.services.session_service import SessionService
    from palatium_ai.domain.projects.ports import ProjectStore
    from palatium_ai.domain.sessions.models import SessionRecord


class ProjectService:
    """High-level project mutations with audit (040) and pin ownership checks."""

    def __init__(
        self,
        store: ProjectStore,
        *,
        session_service: SessionService,
    ) -> None:
        self._store = store
        self._session_service = session_service

    async def create(self, *, user_id: str, title: str) -> ProjectRecord:
        project = await self._store.create(user_id=user_id, title=title)
        await self._audit(
            event="project_created",
            conversation_id=str(project.id),
            payload={"user_id": user_id, "project_id": str(project.id)},
        )
        return project

    async def list_projects(
        self,
        *,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ProjectRecord]:
        return await self._store.list_for_user(user_id=user_id, limit=limit, offset=offset)

    async def rename(self, *, user_id: str, project_id: UUID, title: str) -> ProjectRecord:
        project = await self._store.rename(user_id=user_id, project_id=project_id, title=title)
        if project is None:
            raise ProjectNotFoundError(f"Project '{project_id}' not found")
        await self._audit(
            event="project_renamed",
            conversation_id=str(project.id),
            payload={"user_id": user_id, "project_id": str(project.id)},
        )
        return project

    async def delete(self, *, user_id: str, project_id: UUID) -> None:
        deleted = await self._store.delete(user_id=user_id, project_id=project_id)
        if not deleted:
            raise ProjectNotFoundError(f"Project '{project_id}' not found")
        await self._audit(
            event="project_deleted",
            conversation_id=str(project_id),
            payload={"user_id": user_id, "project_id": str(project_id)},
        )

    async def require_owned(self, *, user_id: str, project_id: UUID) -> ProjectRecord:
        project = await self._store.get_for_user(user_id=user_id, project_id=project_id)
        if project is None:
            raise ProjectNotFoundError(f"Project '{project_id}' not found")
        return project

    async def pin_session(
        self,
        *,
        thread_id: str,
        user_id: str,
        project_id: str | None,
        is_admin: bool = False,
    ) -> SessionRecord:
        """Assign or clear ``sessions.project_id`` after ownership checks."""
        existing = await self._session_service.get_session(thread_id=thread_id)
        if existing is None:
            raise LookupError(f"Session '{thread_id}' not found")
        await self._session_service.assert_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            is_admin=is_admin,
            allow_missing=False,
        )
        cleaned: str | None = None
        if project_id is not None:
            stripped = project_id.strip()
            if stripped:
                try:
                    pid = UUID(stripped)
                except ValueError as exc:
                    raise ProjectNotFoundError(f"Invalid project id '{stripped}'") from exc
                await self.require_owned(user_id=user_id, project_id=pid)
                cleaned = str(pid)
        session = await self._session_service.set_project_id(
            thread_id=thread_id,
            project_id=cleaned,
        )
        await self._audit(
            event="session_project_pinned" if cleaned else "session_project_unpinned",
            conversation_id=thread_id,
            payload={
                "user_id": user_id,
                "project_id": cleaned or "",
            },
        )
        return session

    @staticmethod
    async def _audit(*, event: str, conversation_id: str, payload: dict[str, str]) -> None:
        await get_audit_logger().append_async(
            timestamp=datetime.now(UTC).isoformat(),
            conversation_id=conversation_id,
            event=event,
            metadata=payload,
        )
