"""W10 P0.4 — original blob SHA-256 seal + fail-closed verify."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from palatium_ai.core.types.digest import SHA256_HEX_LENGTH
from palatium_ai.domain.attachments.errors import AttachmentIntegrityError
from palatium_ai.domain.attachments.integrity import content_sha256_hex, verify_attachment_bytes
from palatium_ai.domain.attachments.models import Attachment


def _attachment(*, digest: str | None) -> Attachment:
    return Attachment(
        id=uuid4(),
        user_id="owner",
        thread_id="t1",
        filename="doc.pdf",
        mime_type="application/pdf",
        size_bytes=4,
        blob_key="attachments/x",
        mode="attach",
        status="ready",
        content_sha256=digest,
        created_at=datetime.now(UTC),
    )


def test_content_sha256_hex_is_stable_lowercase() -> None:
    digest = content_sha256_hex(b"abcd")
    assert len(digest) == SHA256_HEX_LENGTH
    assert digest == digest.lower()
    assert digest == content_sha256_hex(b"abcd")


def test_verify_skips_legacy_unsealed_rows() -> None:
    verify_attachment_bytes(_attachment(digest=None), b"anything")


def test_verify_accepts_matching_seal() -> None:
    data = b"payload-bytes"
    verify_attachment_bytes(_attachment(digest=content_sha256_hex(data)), data)


def test_verify_fails_closed_on_mismatch() -> None:
    sealed = _attachment(digest=content_sha256_hex(b"original"))
    with pytest.raises(AttachmentIntegrityError):
        verify_attachment_bytes(sealed, b"tampered")


def test_attachment_rejects_non_hex_digest() -> None:
    with pytest.raises(ValueError, match="content_sha256"):
        _attachment(digest="z" * SHA256_HEX_LENGTH)
