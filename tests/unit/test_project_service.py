# tests/unit/test_project_service.py

"""ProjectService pin ownership + create path (P2)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from palatium_ai.application.services.project_service import ProjectService
from palatium_ai.domain.projects.errors import ProjectNotFoundError
from palatium_ai.domain.projects.models import ProjectRecord
from palatium_ai.domain.sessions.models import SessionRecord

_NOW = datetime.now(UTC)


@pytest.fixture()
def audit_mock(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    append = AsyncMock()
    monkeypatch.setattr(
        "palatium_ai.application.services.project_service.get_audit_logger",
        lambda: MagicMock(append_async=append),
    )
    return append


@pytest.mark.asyncio()
async def test_create_audits(audit_mock: AsyncMock) -> None:
    store = AsyncMock()
    project = ProjectRecord(
        id=uuid4(),
        user_id="user-1",
        title="Alpha",
        created_at=_NOW,
        updated_at=_NOW,
    )
    store.create = AsyncMock(return_value=project)
    service = ProjectService(store, session_service=AsyncMock())

    result = await service.create(user_id="user-1", title="Alpha")

    assert result.id == project.id
    audit_mock.assert_awaited()
    assert audit_mock.await_args.kwargs["event"] == "project_created"


@pytest.mark.asyncio()
async def test_pin_rejects_unknown_project(audit_mock: AsyncMock) -> None:
    store = AsyncMock()
    store.get_for_user = AsyncMock(return_value=None)
    session_service = AsyncMock()
    session_service.get_session = AsyncMock(
        return_value=SessionRecord(
            id=uuid4(),
            thread_id="t1",
            user_id="user-1",
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    session_service.assert_thread_access = AsyncMock(return_value=None)
    service = ProjectService(store, session_service=session_service)

    with pytest.raises(ProjectNotFoundError):
        await service.pin_session(
            thread_id="t1",
            user_id="user-1",
            project_id=str(uuid4()),
        )
    session_service.set_project_id.assert_not_called()
    audit_mock.assert_not_awaited()


@pytest.mark.asyncio()
async def test_pin_and_unpin(audit_mock: AsyncMock) -> None:
    project_id = uuid4()
    store = AsyncMock()
    store.get_for_user = AsyncMock(
        return_value=ProjectRecord(
            id=project_id,
            user_id="user-1",
            title="Alpha",
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    session_service = AsyncMock()
    session = SessionRecord(
        id=uuid4(),
        thread_id="t1",
        user_id="user-1",
        created_at=_NOW,
        updated_at=_NOW,
    )
    session_service.get_session = AsyncMock(return_value=session)
    session_service.assert_thread_access = AsyncMock(return_value=session)
    pinned = session.model_copy(update={"project_id": str(project_id)})
    session_service.set_project_id = AsyncMock(return_value=pinned)
    service = ProjectService(store, session_service=session_service)

    result = await service.pin_session(
        thread_id="t1",
        user_id="user-1",
        project_id=str(project_id),
    )
    assert result.project_id == str(project_id)

    session_service.set_project_id = AsyncMock(return_value=session.model_copy(update={"project_id": None}))
    unpinned = await service.pin_session(thread_id="t1", user_id="user-1", project_id=None)
    assert unpinned.project_id is None
    assert audit_mock.await_count == 2
