# tests/unit/test_documents_ingest_api.py

"""Documents ingest API routes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from palatium_ai.domain.agents.text_ingestor import TextChunk, TextIngestorOutput, TextIngestorTaskResult
from palatium_ai.domain.hitl.cards import HITLCardView, default_tool_approval_options
from palatium_ai.presentation.api.routers import documents
from palatium_ai.presentation.security.principal import AuthPrincipal


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(documents.router, prefix="/documents")

    prepare_result = TextIngestorTaskResult(
        task_id="prep-1",
        agent_role="text_ingestor",
        status="success",
        confidence=0.9,
        output=TextIngestorOutput(
            chunks=(
                TextChunk(index=0, text="one", char_start=0, char_end=3),
                TextChunk(index=1, text="two", char_start=4, char_end=7),
            ),
            chunking_strategy="paragraph",
            normalized_char_count=7,
        ),
    )
    from datetime import UTC, datetime

    card = HITLCardView(
        card_id="hitl_ingest",
        thread_id="thread-1",
        task_id="doc-ingest-abc",
        purpose="mcp_tool_approval",
        title="Approve MCP tool: platform.ingest_document",
        body="write",
        options=default_tool_approval_options(),
        risk_score=0.85,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC),
        owner_user_id="user-1",
        org_id="org-1",
    )
    ingest_service = SimpleNamespace(
        prepare_chunks=AsyncMock(return_value=prepare_result),
        request_commit=AsyncMock(return_value=card),
    )
    resources = SimpleNamespace(
        session_service=AsyncMock(),
        document_ingest_service=ingest_service,
    )
    monkeypatch.setattr(documents, "get_app_resources", lambda _app: resources)
    monkeypatch.setattr(
        documents,
        "get_principal",
        lambda _req: AuthPrincipal(subject="user-1", org_id="org-1", roles=frozenset({"user"})),
    )
    monkeypatch.setattr(documents, "load_session_for_principal", AsyncMock())
    return TestClient(app)


def test_ingest_prepare_returns_chunks(api_client: TestClient) -> None:
    response = api_client.post(
        "/documents/ingest/prepare",
        json={"thread_id": "thread-1", "raw_text": "one\n\ntwo"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["chunk_count"] == 2
    assert payload["status"] == "success"
    assert payload["strategy"] == "paragraph"


def test_ingest_commit_returns_hitl_card(api_client: TestClient) -> None:
    response = api_client.post(
        "/documents/ingest/commit",
        json={"thread_id": "thread-1", "prepare_task_id": "prep-1"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["purpose"] == "mcp_tool_approval"
    assert payload["task_id"].startswith("doc-ingest-")
