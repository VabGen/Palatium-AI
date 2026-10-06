# tests/unit/test_attachments_api.py

"""Attachment API routes: intake, status, HITL-gated indexing, deletion (020).

The router is a thin adapter, so these tests check three things only:
1. every service call is made with the *authenticated* subject (never a client value);
2. typed domain errors map onto the documented HTTP statuses;
3. a disabled subsystem answers 503, and the response never leaks blob keys.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from palatium_ai.application.services.attachment_service import AttachmentSweepResult, AttachmentUploadTicket
from palatium_ai.core.config.security import SecurityConfig
from palatium_ai.domain.agents.intent import IntentClassifierOutput, IntentTaskResult
from palatium_ai.domain.attachments.errors import (
    AttachmentIntakeRejectedError,
    AttachmentModeMismatchError,
    AttachmentNotFoundError,
    AttachmentNotUsableError,
    AttachmentRestoreNotAllowedError,
    AttachmentUploadTooLargeError,
)
from palatium_ai.domain.attachments.models import Attachment
from palatium_ai.domain.hitl.cards import HITLCardView, default_tool_approval_options
from palatium_ai.domain.sessions.models import SessionRecord
from palatium_ai.presentation.api.routers import attachments, intents
from palatium_ai.presentation.security.principal import AuthPrincipal

if TYPE_CHECKING:
    import pytest

_ATTACHMENT_ID = UUID("11111111-2222-3333-4444-555555555555")
_NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _attachment(*, mode: str = "attach", status: str = "ready") -> Attachment:
    return Attachment(
        id=_ATTACHMENT_ID,
        user_id="user-1",
        thread_id="thread-1",
        filename="contract.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        blob_key=f"attachments/{_ATTACHMENT_ID}",
        mode=mode,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        page_count=2,
        created_at=_NOW,
    )


def _card() -> HITLCardView:
    return HITLCardView(
        card_id="hitl_att_index",
        thread_id="thread-1",
        task_id="att-index-abc",
        purpose="mcp_tool_approval",
        title="Approve MCP tool: platform.ingest_document",
        body="write",
        options=default_tool_approval_options(),
        risk_score=0.85,
        created_at=_NOW,
        expires_at=_NOW,
        owner_user_id="user-1",
        org_id="org-1",
    )


class _FakeAttachmentService:
    """Records the arguments the router forwarded, so ownership can be asserted."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.init_calls: list[dict[str, object]] = []
        self.complete_calls: list[dict[str, object]] = []
        self.receive_calls: list[dict[str, object]] = []
        self.list_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []
        self.index_calls: list[dict[str, object]] = []
        self.restore_calls: list[dict[str, object]] = []
        self.compliance_calls: list[dict[str, object]] = []
        self.connector_list_calls: list[dict[str, object]] = []
        self.connector_import_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []
        self.sweep_calls: list[str] = []
        self.sweep_result = AttachmentSweepResult()
        #: Mirrors the service property the router reads to cap the request body.
        self.max_upload_bytes = 1024

    def _raise_if_needed(self) -> None:
        if self.error is not None:
            raise self.error

    async def receive_upload(self, **kwargs: object) -> Attachment:
        self.receive_calls.append(kwargs)
        self._raise_if_needed()
        return _attachment(status="uploaded")

    async def sweep_expired(self, *, user_id: str) -> AttachmentSweepResult:
        self.sweep_calls.append(user_id)
        self._raise_if_needed()
        return self.sweep_result

    async def init_upload(self, **kwargs: object) -> AttachmentUploadTicket:
        self.init_calls.append(kwargs)
        self._raise_if_needed()
        return AttachmentUploadTicket(attachment_id=_ATTACHMENT_ID, upload_url="https://blob/put", expires_at=_NOW)

    async def complete_upload(self, **kwargs: object) -> Attachment:
        self.complete_calls.append(kwargs)
        self._raise_if_needed()
        return _attachment(status="scanning")

    async def list_for_thread(self, **kwargs: object) -> list[Attachment]:
        self.list_calls.append(kwargs)
        self._raise_if_needed()
        return [_attachment()]

    async def get(self, **kwargs: object) -> Attachment:
        self.get_calls.append(kwargs)
        self._raise_if_needed()
        return _attachment()

    async def request_index(self, **kwargs: object) -> HITLCardView:
        self.index_calls.append(kwargs)
        self._raise_if_needed()
        return _card()

    async def request_quarantine_restore(self, **kwargs: object) -> HITLCardView:
        self.restore_calls.append(kwargs)
        self._raise_if_needed()
        return _card().model_copy(update={"task_id": "att-restore-xyz"})

    async def compliance_export_for_thread(self, **kwargs: object) -> tuple[object, ...]:
        self.compliance_calls.append(kwargs)
        self._raise_if_needed()
        from palatium_ai.application.services.attachment_service import AttachmentComplianceRecord

        row = _attachment()
        return (
            AttachmentComplianceRecord(
                id=row.id,
                filename=row.filename,
                mime_type=row.mime_type,
                status=row.status,
                rejection_reason=row.rejection_reason,
                created_at=row.created_at,
                expires_at=row.expires_at,
                page_count=row.page_count,
                size_bytes=row.size_bytes,
                contains_pii=row.contains_pii,
            ),
        )

    async def list_connector_sources(self, **kwargs: object) -> tuple[object, ...]:
        self.connector_list_calls.append(kwargs)
        self._raise_if_needed()
        from palatium_ai.domain.ports.attachment_connector import AttachmentConnectorSource

        return (
            AttachmentConnectorSource(
                id="edms",
                kind="edms",
                label="EDMS (Канцлер NEXT)",
                available=False,
                reason="EDMS MCP import not wired yet (092)",
            ),
        )

    async def request_connector_import(self, **kwargs: object) -> None:
        self.connector_import_calls.append(kwargs)
        self._raise_if_needed()
        from palatium_ai.domain.attachments.errors import AttachmentConnectorUnavailableError

        raise AttachmentConnectorUnavailableError(
            connector_id=str(kwargs.get("connector_id", "edms")),
            reason="EDMS MCP import not wired yet (092)",
        )

    async def delete(self, **kwargs: object) -> None:
        self.delete_calls.append(kwargs)
        self._raise_if_needed()


def _app(
    monkeypatch: pytest.MonkeyPatch,
    service: object,
    *,
    roles: frozenset[str] = frozenset({"user"}),
) -> TestClient:
    """Mount the router with a stubbed resources object and an authenticated caller."""
    app = FastAPI()
    app.include_router(attachments.router, prefix="/attachments")
    app.state.security_config = SecurityConfig(manager_roles="manager,admin", admin_roles="admin")
    resources = SimpleNamespace(session_service=AsyncMock(), attachment_service=service)
    monkeypatch.setattr(attachments, "get_app_resources", lambda _app: resources)
    monkeypatch.setattr(
        attachments,
        "get_principal",
        lambda _req: AuthPrincipal(subject="user-1", org_id="org-1", roles=roles),
    )
    monkeypatch.setattr(attachments, "load_session_for_principal", AsyncMock())
    return TestClient(app)


def _client(
    monkeypatch: pytest.MonkeyPatch, *, error: Exception | None = None
) -> tuple[TestClient, _FakeAttachmentService]:
    service = _FakeAttachmentService(error=error)
    return _app(monkeypatch, service), service


def test_init_upload_returns_presigned_target(monkeypatch: pytest.MonkeyPatch) -> None:
    client, service = _client(monkeypatch)

    response = client.post(
        "/attachments/init",
        json={
            "thread_id": "thread-1",
            "filename": "contract.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 1024,
            "mode": "attach",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["attachment_id"] == str(_ATTACHMENT_ID)
    assert payload["upload_url"] == "https://blob/put"
    assert payload["mode"] == "attach"
    # Ownership is taken from the principal, never from the request body (020).
    assert service.init_calls == [
        {
            "user_id": "user-1",
            "filename": "contract.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 1024,
            "mode": "attach",
            "thread_id": "thread-1",
            "expires_in_seconds": None,
            "project_id": None,
        }
    ]


def test_init_upload_rejects_unknown_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    client, service = _client(monkeypatch)

    response = client.post(
        "/attachments/init",
        json={
            "thread_id": "thread-1",
            "filename": "contract.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 1024,
            "mode": "execute",
        },
    )

    assert response.status_code == 422
    assert service.init_calls == []


def test_init_upload_maps_intake_rejection_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(monkeypatch, error=AttachmentIntakeRejectedError("mime_not_allowed", filename="old.doc"))

    response = client.post(
        "/attachments/init",
        json={
            "thread_id": "thread-1",
            "filename": "old.doc",
            "mime_type": "application/msword",
            "size_bytes": 1024,
        },
    )

    assert response.status_code == 400
    assert "mime_not_allowed" in response.json()["detail"]


def test_init_upload_allows_a_fresh_thread_without_a_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: attaching before the first message answered 404 "Session not found".

    The client mints the thread id locally and the session is only created by the
    first turn, so ``init`` must treat a missing session as "may be created" (like
    ``IntentService.classify``) while an existing thread is still owner-checked.
    """
    app = FastAPI()
    app.include_router(attachments.router, prefix="/attachments")
    service = _FakeAttachmentService()
    resources = SimpleNamespace(session_service=AsyncMock(), attachment_service=service)
    loader = AsyncMock()
    monkeypatch.setattr(attachments, "get_app_resources", lambda _app: resources)
    monkeypatch.setattr(
        attachments,
        "get_principal",
        lambda _req: AuthPrincipal(subject="user-1", org_id="org-1", roles=frozenset({"user"})),
    )
    monkeypatch.setattr(attachments, "load_session_for_principal", loader)

    response = TestClient(app).post(
        "/attachments/init",
        json={
            "thread_id": "thread-fresh",
            "filename": "contract.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 1024,
        },
    )

    assert response.status_code == 201
    assert loader.await_args is not None
    assert loader.await_args.kwargs["allow_missing"] is True


def test_disabled_attachments_answer_503(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _app(monkeypatch, None)

    response = client.get(f"/attachments/{_ATTACHMENT_ID}")

    assert response.status_code == 503
    assert "disabled" in response.json()["detail"].lower()


def test_complete_upload_returns_pipeline_state(monkeypatch: pytest.MonkeyPatch) -> None:
    client, service = _client(monkeypatch)

    response = client.post(f"/attachments/{_ATTACHMENT_ID}/complete")

    assert response.status_code == 200
    assert response.json()["status"] == "scanning"
    assert service.complete_calls == [{"attachment_id": _ATTACHMENT_ID, "user_id": "user-1"}]


def test_complete_upload_of_foreign_attachment_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(monkeypatch, error=AttachmentNotFoundError(_ATTACHMENT_ID))

    response = client.post(f"/attachments/{_ATTACHMENT_ID}/complete")

    assert response.status_code == 404


def test_upload_content_forwards_the_body_and_the_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    """The proxied path stores the bytes for the *authenticated* owner, never a client id."""
    client, service = _client(monkeypatch)

    response = client.put(
        f"/attachments/{_ATTACHMENT_ID}/content",
        content=b"hello",
        headers={"Content-Type": "text/plain"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "uploaded"
    assert service.receive_calls == [{"attachment_id": _ATTACHMENT_ID, "user_id": "user-1", "data": b"hello"}]


def test_upload_content_over_the_cap_is_413(monkeypatch: pytest.MonkeyPatch) -> None:
    client, service = _client(monkeypatch)
    service.max_upload_bytes = 4

    response = client.put(f"/attachments/{_ATTACHMENT_ID}/content", content=b"12345")

    assert response.status_code == 413
    assert service.receive_calls == []


def test_upload_content_caps_a_chunked_body_without_content_length(monkeypatch: pytest.MonkeyPatch) -> None:
    """A chunked body carries no Content-Length claim, so the stream itself must be capped."""
    client, service = _client(monkeypatch)
    service.max_upload_bytes = 4

    response = client.put(
        f"/attachments/{_ATTACHMENT_ID}/content",
        content=iter([b"123", b"456"]),
    )

    assert response.status_code == 413
    assert service.receive_calls == []


def test_upload_content_with_an_empty_body_is_400(monkeypatch: pytest.MonkeyPatch) -> None:
    client, service = _client(monkeypatch)

    response = client.put(f"/attachments/{_ATTACHMENT_ID}/content", content=b"")

    assert response.status_code == 400
    assert service.receive_calls == []


def test_upload_content_of_a_ready_attachment_is_409(monkeypatch: pytest.MonkeyPatch) -> None:
    error = AttachmentNotUsableError(_ATTACHMENT_ID, state="ready")
    client, _ = _client(monkeypatch, error=error)

    response = client.put(f"/attachments/{_ATTACHMENT_ID}/content", content=b"hello")

    assert response.status_code == 409


def test_upload_content_maps_a_typed_too_large_error_to_413(monkeypatch: pytest.MonkeyPatch) -> None:
    """The service re-checks the cap, so a non-HTTP caller cannot slip past the router."""
    error = AttachmentUploadTooLargeError(_ATTACHMENT_ID, size_bytes=10, max_size_bytes=4)
    client, _ = _client(monkeypatch, error=error)

    response = client.put(f"/attachments/{_ATTACHMENT_ID}/content", content=b"hello")

    assert response.status_code == 413


def test_upload_content_is_unavailable_when_attachments_are_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _app(monkeypatch, None)

    response = client.put(f"/attachments/{_ATTACHMENT_ID}/content", content=b"hello")

    assert response.status_code == 503


def test_list_attachments_serialises_items(monkeypatch: pytest.MonkeyPatch) -> None:
    client, service = _client(monkeypatch)

    response = client.get("/attachments", params={"thread_id": "thread-1"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["thread_id"] == "thread-1"
    assert [item["attachment_id"] for item in payload["items"]] == [str(_ATTACHMENT_ID)]
    assert service.list_calls == [{"thread_id": "thread-1", "user_id": "user-1"}]


def test_get_attachment_returns_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    client, service = _client(monkeypatch)

    response = client.get(f"/attachments/{_ATTACHMENT_ID}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "contract.pdf"
    assert payload["mode"] == "attach"
    assert service.get_calls == [{"attachment_id": _ATTACHMENT_ID, "user_id": "user-1"}]


def test_attachment_response_never_exposes_blob_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(monkeypatch)

    payload = client.get(f"/attachments/{_ATTACHMENT_ID}").json()

    assert "blob_key" not in payload
    assert "derived_text_key" not in payload


def test_restore_request_returns_hitl_card(monkeypatch: pytest.MonkeyPatch) -> None:
    client, service = _client(monkeypatch)

    response = client.post(
        f"/attachments/{_ATTACHMENT_ID}/restore-request",
        json={"thread_id": "thread-1"},
    )

    assert response.status_code == 200
    assert response.json()["task_id"].startswith("att-restore-")
    assert service.restore_calls == [
        {
            "attachment_id": _ATTACHMENT_ID,
            "user_id": "user-1",
            "thread_id": "thread-1",
            "org_id": "org-1",
        }
    ]


def test_restore_request_rejects_malware_quarantine(monkeypatch: pytest.MonkeyPatch) -> None:
    error = AttachmentRestoreNotAllowedError(
        _ATTACHMENT_ID,
        status="quarantined",
        rejection_reason="malware_detected",
    )
    client, _ = _client(monkeypatch, error=error)

    response = client.post(
        f"/attachments/{_ATTACHMENT_ID}/restore-request",
        json={"thread_id": "thread-1"},
    )

    assert response.status_code == 409


def test_compliance_export_requires_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _FakeAttachmentService()
    client = _app(monkeypatch, service, roles=frozenset({"user"}))

    response = client.get("/attachments/compliance-export", params={"thread_id": "thread-1"})

    assert response.status_code == 403
    assert service.compliance_calls == []


def test_compliance_export_returns_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _FakeAttachmentService()
    session = SessionRecord(
        id=uuid4(),
        thread_id="thread-1",
        user_id="owner-1",
        created_at=_NOW,
        updated_at=_NOW,
    )
    session_service = AsyncMock()
    session_service.get_session = AsyncMock(return_value=session)
    client = _app(monkeypatch, service, roles=frozenset({"manager"}))
    # `_app` stubs resources; replace session_service after mount so ownership resolves.
    monkeypatch.setattr(
        attachments,
        "get_app_resources",
        lambda _app: SimpleNamespace(session_service=session_service, attachment_service=service),
    )

    response = client.get("/attachments/compliance-export", params={"thread_id": "thread-1"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["thread_id"] == "thread-1"
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["filename"] == "contract.pdf"
    assert "safe_text" not in item
    assert "blob_key" not in item
    assert service.compliance_calls == [{"thread_id": "thread-1", "owner_user_id": "owner-1"}]


def test_list_connectors_returns_edms_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    client, service = _client(monkeypatch)

    response = client.get("/attachments/connectors")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == "edms"
    assert payload["items"][0]["available"] is False
    assert service.connector_list_calls == [{"user_id": "user-1", "org_id": "org-1"}]


def test_connector_import_returns_501(monkeypatch: pytest.MonkeyPatch) -> None:
    client, service = _client(monkeypatch)

    response = client.post(
        "/attachments/connectors/edms/import",
        json={"thread_id": "thread-1", "remote_ref": "doc:42"},
    )

    assert response.status_code == 501
    assert service.connector_import_calls == [
        {
            "connector_id": "edms",
            "remote_ref": "doc:42",
            "user_id": "user-1",
            "org_id": "org-1",
            "thread_id": "thread-1",
            "project_id": None,
        }
    ]


def test_request_index_returns_hitl_card(monkeypatch: pytest.MonkeyPatch) -> None:
    client, service = _client(monkeypatch)

    response = client.post(
        f"/attachments/{_ATTACHMENT_ID}/index",
        json={"thread_id": "thread-1", "document_title": "Contract 2026"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["purpose"] == "mcp_tool_approval"
    assert payload["task_id"].startswith("att-index-")
    # Nothing is written here: the write only happens after the user approves the card.
    assert service.index_calls == [
        {
            "attachment_id": _ATTACHMENT_ID,
            "user_id": "user-1",
            "thread_id": "thread-1",
            "org_id": "org-1",
            "document_title": "Contract 2026",
        }
    ]


def test_index_of_attached_file_is_409(monkeypatch: pytest.MonkeyPatch) -> None:
    error = AttachmentModeMismatchError(_ATTACHMENT_ID, expected="index", actual="attach")
    client, _ = _client(monkeypatch, error=error)

    response = client.post(f"/attachments/{_ATTACHMENT_ID}/index", json={"thread_id": "thread-1"})

    assert response.status_code == 409


def test_index_of_quarantined_file_is_409(monkeypatch: pytest.MonkeyPatch) -> None:
    error = AttachmentNotUsableError(_ATTACHMENT_ID, state="quarantined")
    client, _ = _client(monkeypatch, error=error)

    response = client.post(f"/attachments/{_ATTACHMENT_ID}/index", json={"thread_id": "thread-1"})

    assert response.status_code == 409


def test_index_without_hitl_service_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(
        monkeypatch,
        error=RuntimeError("attachment indexing requires a configured HITL service"),
    )

    response = client.post(f"/attachments/{_ATTACHMENT_ID}/index", json={"thread_id": "thread-1"})

    assert response.status_code == 503


def test_delete_attachment_returns_204(monkeypatch: pytest.MonkeyPatch) -> None:
    client, service = _client(monkeypatch)
    attachment_id = uuid4()

    response = client.delete(f"/attachments/{attachment_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert service.delete_calls == [{"attachment_id": attachment_id, "user_id": "user-1"}]


def test_delete_missing_attachment_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(monkeypatch, error=AttachmentNotFoundError(_ATTACHMENT_ID))

    response = client.delete(f"/attachments/{_ATTACHMENT_ID}")

    assert response.status_code == 404


def test_sweep_returns_retention_counters_for_the_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    client, service = _client(monkeypatch)
    service.sweep_result = AttachmentSweepResult(considered=3, purged=2, failed=1, skipped=0)

    response = client.post("/attachments/sweep")

    assert response.status_code == 200
    assert response.json() == {"considered": 3, "purged": 2, "failed": 1, "skipped": 0}
    # Retention is always scoped to the authenticated owner, never to a client value.
    assert service.sweep_calls == ["user-1"]


def test_sweep_is_unavailable_when_attachments_are_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _app(monkeypatch, None)

    response = client.post("/attachments/sweep")

    assert response.status_code == 503


class _RecordingIntentService:
    """Captures the dialog-turn call so the router's attachment plumbing is assertable."""

    def __init__(self, *, result: IntentTaskResult | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.classify_calls: list[dict[str, object]] = []
        self.process_calls: list[dict[str, object]] = []

    async def classify(self, **kwargs: object) -> IntentTaskResult:
        self.classify_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result

    async def process(self, **kwargs: object) -> object:
        self.process_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        raise AssertionError("this fake is only used for the failure path")


def _intents_client(monkeypatch: pytest.MonkeyPatch, service: object) -> TestClient:
    app = FastAPI()
    app.include_router(intents.router, prefix="/intents")
    monkeypatch.setattr(intents, "get_app_resources", lambda _app: SimpleNamespace(intent_service=service))
    monkeypatch.setattr(
        intents,
        "get_principal",
        lambda _req: AuthPrincipal(subject="user-1", org_id="org-1", roles=frozenset({"user"})),
    )
    monkeypatch.setattr(intents, "principal_is_admin", lambda _req, _principal: False)
    return TestClient(app)


def test_dialog_turn_forwards_attachment_ids_to_intent_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """The turn must reach the service with the ids, so fencing happens before any LLM."""
    result = IntentTaskResult(
        task_id="task-1",
        agent_role="intent_classifier",
        status="success",
        confidence=0.9,
        output=IntentClassifierOutput(
            task_kind="knowledge_request",
            requires_mcp=False,
            confidence=0.9,
            reasoning="Question about the attached file",
        ),
    )
    service = _RecordingIntentService(result=result)
    client = _intents_client(monkeypatch, service)

    response = client.post(
        "/intents/classify",
        json={
            "text": "What are the delivery terms?",
            "thread_id": "thread-1",
            "attachment_ids": [str(_ATTACHMENT_ID)],
        },
    )

    assert response.status_code == 200
    assert service.classify_calls[0]["attachment_ids"] == [_ATTACHMENT_ID]
    assert service.classify_calls[0]["user_id"] == "user-1"


def test_dialog_turn_with_unusable_attachment_is_409(monkeypatch: pytest.MonkeyPatch) -> None:
    """A quarantined file fails the turn loudly instead of being quietly dropped (020)."""
    service = _RecordingIntentService(error=AttachmentNotUsableError(_ATTACHMENT_ID, state="quarantined"))
    client = _intents_client(monkeypatch, service)

    response = client.post(
        "/intents/process",
        json={
            "text": "Summarise the attached contract",
            "thread_id": "thread-1",
            "attachment_ids": [str(_ATTACHMENT_ID)],
        },
    )

    assert response.status_code == 409
