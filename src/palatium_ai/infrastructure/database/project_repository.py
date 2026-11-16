# src/palatium_ai/infrastructure/database/project_repository.py

"""Postgres ProjectStore with FORCE RLS binding (060)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update

from palatium_ai.domain.projects.models import ProjectRecord
from palatium_ai.infrastructure.database.models import ProjectORM
from palatium_ai.infrastructure.database.rls import set_rls_user_scope

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _project_from_orm(entity: ProjectORM) -> ProjectRecord:
    return ProjectRecord(
        id=entity.id,
        user_id=entity.user_id,
        title=entity.title,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


class PostgresProjectRepository:
    """SQLAlchemy adapter implementing ``ProjectStore``."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, *, user_id: str, title: str) -> ProjectRecord:
        """Insert a new project owned by ``user_id``."""
        cleaned_title = title.strip()
        if not cleaned_title:
            msg = "project title must be non-empty"
            raise ValueError(msg)
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            entity = ProjectORM(id=uuid4(), user_id=user_id, title=cleaned_title)
            session.add(entity)
            await session.commit()
            await session.refresh(entity)
            return _project_from_orm(entity)

    async def list_for_user(
        self,
        *,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ProjectRecord]:
        """Return projects for one owner, newest first."""
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            stmt = (
                select(ProjectORM)
                .where(ProjectORM.user_id == user_id)
                .order_by(ProjectORM.updated_at.desc())
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(stmt)
            return [_project_from_orm(row) for row in result.scalars().all()]

    async def get_for_user(self, *, user_id: str, project_id: UUID) -> ProjectRecord | None:
        """Fetch one project if owned by ``user_id``."""
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            stmt = select(ProjectORM).where(
                ProjectORM.id == project_id,
                ProjectORM.user_id == user_id,
            )
            entity = (await session.execute(stmt)).scalar_one_or_none()
            return _project_from_orm(entity) if entity is not None else None

    async def rename(
        self,
        *,
        user_id: str,
        project_id: UUID,
        title: str,
    ) -> ProjectRecord | None:
        """Update title; ``None`` when missing or not owned."""
        cleaned_title = title.strip()
        if not cleaned_title:
            msg = "project title must be non-empty"
            raise ValueError(msg)
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            result = await session.execute(
                update(ProjectORM)
                .where(ProjectORM.id == project_id, ProjectORM.user_id == user_id)
                .values(title=cleaned_title)
                .returning(ProjectORM)
            )
            entity = result.scalar_one_or_none()
            if entity is None:
                await session.rollback()
                return None
            await session.commit()
            return _project_from_orm(entity)

    async def delete(self, *, user_id: str, project_id: UUID) -> bool:
        """Delete owned project; ``False`` when missing or not owned."""
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            result = await session.execute(
                delete(ProjectORM).where(
                    ProjectORM.id == project_id,
                    ProjectORM.user_id == user_id,
                )
            )
            await session.commit()
            return (result.rowcount or 0) > 0
