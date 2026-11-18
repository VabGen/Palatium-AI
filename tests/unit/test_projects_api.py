# tests/unit/test_projects_api.py

"""Projects API + session pin (P2)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from palatium_ai.domain.projects.errors import ProjectNotFoundError
from palatium_ai.domain.projects.models import ProjectRecord
from palatium_ai.domain.sessions.errors import SessionOwnershipError
from palatium_ai.domain.sessions.models import SessionRecord
from palatium_ai.presentation.api.routers import projects, sessions
from palatium_ai.presentation.security.principal import AuthPrincipal

_NOW = datetime.now(UTC)


def _project(*, user_id: str = "user-1", title: str = "Alpha") -> ProjectRecord:
    return ProjectRecord(
        id=uuid4(),
        user_id=user_id,
        title=title,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _session(*, thread_id: str = "thread-1", project_id: str | None = None) -> SessionRecord:
    return SessionRecord(
        id=uuid4(),
        thread_id=thread_id,
        user_id="user-1",
        project_id=project_id,
        created_at=_NOW,
        updated_at=_NOW,
    )


@pytest.fixture()
def projects_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, AsyncMock]:
    app = FastAPI()
    app.include_router(projects.router, prefix="/api/projects")
    service = AsyncMock()
    resources = SimpleNamespace(project_service=service)
    monkeypatch.setattr(projects, "get_app_resources", lambda _app: resources)
    monkeypatch.setattr(
        projects,
        "get_principal",
        lambda _req: AuthPrincipal(subject="user-1", org_id="org-1", roles=frozenset({"user"})),
    )
    return TestClient(app), service


def test_list_projects(projects_client: tuple[TestClient, AsyncMock]) -> None:
    client, service = projects_client
    row = _project()
    service.list_projects = AsyncMock(return_value=[row])

    response = client.get("/api/projects/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["id"] == str(row.id)
    assert payload["items"][0]["title"] == "Alpha"
    service.list_projects.assert_awaited_once()


def test_create_project(projects_client: tuple[TestClient, AsyncMock]) -> None:
    client, service = projects_client
    row = _project(title="Beta")
    service.create = AsyncMock(return_value=row)

    response = client.post("/api/projects/", json={"title": "Beta"})

    assert response.status_code == 201
    assert response.json()["title"] == "Beta"
    service.create.assert_awaited_once_with(user_id="user-1", title="Beta")


def test_rename_project_not_found(projects_client: tuple[TestClient, AsyncMock]) -> None:
    client, service = projects_client
    pid = uuid4()
    service.rename = AsyncMock(side_effect=ProjectNotFoundError("missing"))

    response = client.patch(f"/api/projects/{pid}", json={"title": "Gamma"})

    assert response.status_code == 404


class _SessionServiceStub:
    """Only the access guard ``patch_session`` calls.

    A bare ``AsyncMock`` cannot serve this name: Mock reserves ``assert*`` for its own
    assertion helpers and raises ``AttributeError`` on the router's method.
    """

    async def assert_thread_access(self, **_kwargs: object) -> None:
        return None


@pytest.fixture()
def pin_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, AsyncMock]:
    app = FastAPI()
    app.include_router(sessions.router, prefix="/api/sessions")
    service = AsyncMock()
    resources = SimpleNamespace(project_service=service, session_service=_SessionServiceStub())
    monkeypatch.setattr(sessions, "get_app_resources", lambda _app: resources)
    monkeypatch.setattr(
        sessions,
        "get_principal",
        lambda _req: AuthPrincipal(subject="user-1", org_id="org-1", roles=frozenset({"user"})),
    )
    monkeypatch.setattr(sessions, "principal_is_admin", lambda _req, _p: False)
    return TestClient(app), service


def test_pin_session(pin_client: tuple[TestClient, AsyncMock]) -> None:
    client, service = pin_client
    project_id = str(uuid4())
    session = _session(project_id=project_id)
    service.pin_session = AsyncMock(return_value=session)

    response = client.patch(
        "/api/sessions/thread-1",
        json={"project_id": project_id},
    )

    assert response.status_code == 200
    assert response.json()["project_id"] == project_id
    service.pin_session.assert_awaited_once()


def test_pin_session_rejects_foreign_project(pin_client: tuple[TestClient, AsyncMock]) -> None:
    client, service = pin_client
    service.pin_session = AsyncMock(side_effect=ProjectNotFoundError("foreign"))

    response = client.patch(
        "/api/sessions/thread-1",
        json={"project_id": str(uuid4())},
    )

    assert response.status_code == 404


def test_pin_session_forbidden(pin_client: tuple[TestClient, AsyncMock]) -> None:
    client, service = pin_client
    service.pin_session = AsyncMock(side_effect=SessionOwnershipError("denied"))

    response = client.patch("/api/sessions/thread-1", json={"project_id": None})

    assert response.status_code == 403
