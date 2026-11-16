"""W10.1 P0.5 — blob retrieval contract (roundtrip / missing / deleted usability)."""

from __future__ import annotations

import hashlib

from uuid import uuid4

import pytest

from palatium_ai.domain.attachments.errors import AttachmentNotFoundError, AttachmentNotUsableError
from palatium_ai.domain.attachments.models import Attachment
from palatium_ai.domain.attachments.read import AttachmentReadRequest
from palatium_ai.domain.ports.blob_store import BlobNotFoundError
from palatium_ai.infrastructure.blob.in_memory_adapter import InMemoryBlobStore


@pytest.mark.asyncio()
async def test_w101_minio_retrieval_roundtrip() -> None:
    store = InMemoryBlobStore(bucket="palatium-attachments")
    payload = b"w101-roundtrip-bytes"
    key = f"attachments/{uuid4().hex}/note.txt"
    await store.write_bytes(key, payload, content_type="text/plain")
    got = await store.read_bytes(key)
    assert got == payload
    assert hashlib.sha256(got).hexdigest() == hashlib.sha256(payload).hexdigest()


@pytest.mark.asyncio()
async def test_w101_minio_missing_object_raises() -> None:
    store = InMemoryBlobStore()
    with pytest.raises(BlobNotFoundError):
        await store.read_bytes(f"attachments/{uuid4().hex}/missing.bin")


@pytest.mark.asyncio()
async def test_w101_minio_deleted_status_blocked() -> None:
    """Rows not in ready/indexed must not be readable (AttachmentReadService gate)."""
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock

    from palatium_ai.application.services.attachment_read_service import AttachmentReadService

    attachment_id = uuid4()
    row = Attachment(
        id=attachment_id,
        user_id="user-a",
        thread_id="thread-a",
        filename="gone.pdf",
        mime_type="application/pdf",
        size_bytes=12,
        blob_key=f"attachments/{attachment_id.hex}/gone.pdf",
        mode="attach",
        status="rejected",
        rejection_reason="malware_detected",
        created_at=datetime.now(UTC),
    )
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=row)
    service = AttachmentReadService(
        repository=repo,
        blob_store=InMemoryBlobStore(),
        pipeline=AsyncMock(),
    )
    with pytest.raises(AttachmentNotUsableError):
        await service.read(AttachmentReadRequest(attachment_id=attachment_id, user_id="user-a"))


@pytest.mark.asyncio()
async def test_w101_minio_idor_blocked() -> None:
    """Owner-scoped get returning None → not found (no cross-user body)."""
    from unittest.mock import AsyncMock

    from palatium_ai.application.services.attachment_read_service import AttachmentReadService

    attachment_id = uuid4()
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=None)  # RLS / owner filter
    service = AttachmentReadService(
        repository=repo,
        blob_store=InMemoryBlobStore(),
        pipeline=AsyncMock(),
    )
    with pytest.raises(AttachmentNotFoundError):
        await service.read(AttachmentReadRequest(attachment_id=attachment_id, user_id="user-b"))
