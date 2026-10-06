"""Attachment aggregate invariants (020, 010)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from pydantic import ValidationError

from palatium_ai.domain.attachments import Attachment

_NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _attachment(**overrides: object) -> Attachment:
    payload: dict[str, object] = {
        "id": uuid4(),
        "user_id": "user-1",
        "thread_id": "thread-1",
        "filename": "invoice.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 1024,
        "blob_key": "attachments/abc",
        "mode": "attach",
        "status": "pending",
        "created_at": _NOW,
    }
    payload.update(overrides)
    return Attachment(**payload)  # type: ignore[arg-type]


def test_pending_attachment_is_not_usable() -> None:
    attachment = _attachment()
    assert not attachment.is_usable
    assert attachment.rejection_reason is None


def test_ready_and_indexed_attachments_are_usable() -> None:
    assert _attachment(status="ready").is_usable
    assert _attachment(status="indexed").is_usable


def test_naive_created_at_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _attachment(created_at=datetime(2026, 9, 25, 12, 0))


def test_naive_expires_at_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _attachment(expires_at=datetime(2026, 9, 26, 12, 0))


def test_aware_expires_at_is_accepted() -> None:
    attachment = _attachment(expires_at=_NOW + timedelta(hours=1))
    assert attachment.expires_at == _NOW + timedelta(hours=1)


def test_rejected_status_requires_a_typed_reason() -> None:
    with pytest.raises(ValidationError):
        _attachment(status="rejected")
    assert _attachment(status="rejected", rejection_reason="size_exceeded").rejection_reason == "size_exceeded"


def test_quarantined_status_requires_a_typed_reason() -> None:
    with pytest.raises(ValidationError):
        _attachment(status="quarantined")
    assert _attachment(status="quarantined", rejection_reason="malware_detected").rejection_reason == (
        "malware_detected"
    )


def test_unknown_status_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _attachment(status="weird")


def test_is_expired_tracks_ttl() -> None:
    assert not _attachment().is_expired
    assert _attachment(expires_at=_NOW - timedelta(seconds=1)).is_expired
    assert not _attachment(expires_at=_NOW + timedelta(days=1)).is_expired


def test_aggregate_is_frozen() -> None:
    attachment = _attachment()
    with pytest.raises(ValidationError):
        attachment.status = "ready"  # type: ignore[misc]


def test_model_copy_changes_status_without_mutating_original() -> None:
    attachment = _attachment()
    updated = attachment.model_copy(update={"status": "scanning"})
    assert attachment.status == "pending"
    assert updated.status == "scanning"
