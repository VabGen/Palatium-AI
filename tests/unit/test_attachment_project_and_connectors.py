# tests/unit/test_attachment_project_and_connectors.py

"""Project KB document id + connector catalog (G09/G10)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from palatium_ai.domain.attachments.indexing import AttachmentIndexPayload
from palatium_ai.infrastructure.connectors import DisabledAttachmentConnector


def test_index_payload_encodes_project_document_id() -> None:
    attachment_id = uuid4()
    plain = AttachmentIndexPayload(
        task_id="att-index-1",
        attachment_id=attachment_id,
        user_id="u1",
        thread_id="t1",
    )
    assert plain.knowledge_document_id() == str(attachment_id)

    scoped = plain.model_copy(update={"project_id": "proj-alpha"})
    assert scoped.knowledge_document_id() == f"project:proj-alpha:{attachment_id.hex}"
    assert len(scoped.knowledge_document_id()) <= 128


@pytest.mark.asyncio()
async def test_disabled_connector_advertises_edms_first() -> None:
    sources = await DisabledAttachmentConnector().list_sources(user_id="u1", org_id="o1")
    assert len(sources) == 1
    assert sources[0].kind == "edms"
    assert sources[0].available is False
    assert "092" in sources[0].reason


@pytest.mark.asyncio()
async def test_disabled_connector_import_fails_closed() -> None:
    from palatium_ai.domain.attachments.errors import AttachmentConnectorUnavailableError
    from palatium_ai.domain.ports.attachment_connector import AttachmentConnectorImportRequest

    with pytest.raises(AttachmentConnectorUnavailableError) as exc_info:
        await DisabledAttachmentConnector().request_import(
            AttachmentConnectorImportRequest(
                connector_id="edms",
                remote_ref="doc:123",
                user_id="u1",
                org_id="o1",
                thread_id="th-1",
            )
        )
    assert exc_info.value.connector_id == "edms"
    assert "092" in exc_info.value.reason
