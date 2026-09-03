# tests/unit/test_memory_api.py

"""Memory save/forget API routes."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from palatium_ai.domain.hitl.cards import HITLCardView, default_tool_approval_options
from palatium_ai.presentation.api.routers import memory
from palatium_ai.presentation.security.principal import AuthPrincipal


def _card(*, task_id: str, title: str) -> HITLCardView:
    return HITLCardView(
        card_id="hitl_mem",
        thread_id="thread-1",
        task_id=task_id,
        purpose="mcp_tool_approval",
        title=title,
        body="write",
        options=default_tool_approval_options(),
        risk_score=0.5,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC),
        owner_user_id="user-1",
        org_id="org-1",
    )


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(memory.router, prefix="/api/memory")

    save_service = SimpleNamespace(
        request_save=AsyncMock(
            return_value=_card(
                task_id="mem-save-abc",
                title="Approve MCP tool: platform.save_memory",
            )
        )
    )
    forget_service = SimpleNamespace(
        request_forget=AsyncMock(
            return_value=_card(
                task_id="mem-forget-xyz",
                title="Approve MCP tool: platform.forget_memory",
            )
        )
    )
    consolidate_service = SimpleNamespace(
        request_consolidate=AsyncMock(
            return_value=_card(
                task_id="mem-consolidate-q1",
                title="Approve MCP tool: platform.consolidate_memory",
            )
        )
    )
    resources = SimpleNamespace(
        session_service=AsyncMock(),
        memory_save_service=save_service,
        memory_forget_service=forget_service,
        memory_consolidate_service=consolidate_service,
    )
    monkeypatch.setattr(memory, "get_app_resources", lambda _app: resources)
    monkeypatch.setattr(
        memory,
        "get_principal",
        lambda _req: AuthPrincipal(subject="user-1", org_id="org-1", roles=frozenset({"user"})),
    )
    monkeypatch.setattr(memory, "load_session_for_principal", AsyncMock())
    return TestClient(app)


def test_memory_save_returns_hitl_card(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/memory/save",
        json={
            "thread_id": "thread-1",
            "text": "User prefers Russian.",
            "entry_key": "pref-lang",
            "namespace_kind": "user",
            "memory_type": "preference",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["purpose"] == "mcp_tool_approval"
    assert payload["task_id"].startswith("mem-save-")


def test_memory_forget_returns_hitl_card(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/memory/forget",
        json={
            "thread_id": "thread-1",
            "entry_key": "pref-lang",
            "namespace_kind": "user",
            "scope_id": "user-1",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["purpose"] == "mcp_tool_approval"
    assert payload["task_id"].startswith("mem-forget-")


def test_memory_consolidate_returns_hitl_card(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/memory/consolidate",
        json={"thread_id": "thread-1", "consolidate_task_id": "job-1"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["purpose"] == "mcp_tool_approval"
    assert payload["task_id"].startswith("mem-consolidate-")


def test_memory_save_ownership_error_maps_to_403(api_client: TestClient) -> None:
    resources = memory.get_app_resources(api_client.app)  # type: ignore[arg-type]
    resources.memory_save_service.request_save = AsyncMock(
        side_effect=ValueError("scope_id must match authenticated user")
    )
    response = api_client.post(
        "/api/memory/save",
        json={
            "thread_id": "thread-1",
            "text": "x",
            "entry_key": "k",
            "namespace_kind": "user",
            "scope_id": "user-victim",
        },
    )
    assert response.status_code == 403


def test_http_error_helper_maps_org_claim() -> None:
    from fastapi import status as http_status

    err = memory._http_error_for_memory_validation(ValueError("org namespace requires authenticated org_id"))
    assert err.status_code == http_status.HTTP_403_FORBIDDEN
