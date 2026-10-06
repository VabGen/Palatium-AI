"""AttachmentIntakePolicy — limits, media registry, filename safety, TTL (020/055)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from pydantic import ValidationError

from palatium_ai.domain.attachments import Attachment
from palatium_ai.domain.attachments.policies import (
    DEFAULT_ATTACHMENT_LIMITS,
    SUPPORTED_MEDIA_TYPES,
    AttachmentIntakePolicy,
    AttachmentLimits,
    AttachmentRetentionPolicy,
    IntakeDecision,
)

_NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _validate(**overrides: object) -> IntakeDecision:
    payload: dict[str, object] = {
        "filename": "invoice.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 1024,
    }
    payload.update(overrides)
    return AttachmentIntakePolicy.validate(**payload)  # type: ignore[arg-type]


def test_supported_media_types_are_a_closed_registry() -> None:
    assert "application/pdf" in SUPPORTED_MEDIA_TYPES
    assert "application/x-msdownload" not in SUPPORTED_MEDIA_TYPES


def test_valid_pdf_is_allowed() -> None:
    decision = _validate()
    assert decision.allowed
    assert decision.reason is None
    assert not decision.refused


def test_zero_size_is_refused_as_invalid() -> None:
    assert _validate(size_bytes=0).reason == "size_invalid"


def test_oversized_file_is_refused() -> None:
    assert _validate(size_bytes=DEFAULT_ATTACHMENT_LIMITS.max_size_bytes + 1).reason == "size_exceeded"


def test_unknown_media_type_is_refused() -> None:
    assert _validate(filename="setup.exe", mime_type="application/x-msdownload").reason == "mime_not_allowed"


def test_extension_must_match_declared_media_type() -> None:
    assert _validate(filename="invoice.txt", mime_type="application/pdf").reason == "extension_mismatch"


def test_turn_limit_is_enforced() -> None:
    limit = DEFAULT_ATTACHMENT_LIMITS.max_attachments_per_turn
    assert _validate(existing_count=limit - 1).allowed
    assert _validate(existing_count=limit).reason == "turn_limit_exceeded"


def test_path_traversal_filename_is_reduced_to_basename() -> None:
    decision = _validate(filename="../../etc/passwd.pdf")
    assert decision.allowed
    assert decision.filename == "passwd.pdf"


def test_windows_path_filename_is_reduced_to_basename() -> None:
    assert _validate(filename="C:\\Users\\evil\\invoice.pdf").filename == "invoice.pdf"


def test_control_characters_in_filename_are_refused() -> None:
    decision = _validate(filename="invoice\u0000.pdf")
    assert decision.reason == "filename_invalid"
    assert decision.filename == ""


def test_newline_in_filename_is_refused() -> None:
    assert _validate(filename="invoice\n.pdf").reason == "filename_invalid"


def test_dot_only_filename_is_refused() -> None:
    assert _validate(filename=".").reason == "filename_invalid"


def test_long_filename_is_truncated_but_keeps_its_extension() -> None:
    """Regression: cutting the suffix would silently break the media-type cross-check."""
    decision = AttachmentIntakePolicy.validate(
        filename=f"{'a' * 100}.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        limits=AttachmentLimits(max_filename_chars=32),
    )
    assert decision.allowed
    assert decision.filename.endswith(".pdf")
    assert len(decision.filename) == 32


def test_sanitize_filename_strips_surrounding_whitespace() -> None:
    assert AttachmentIntakePolicy.sanitize_filename("  report.pdf  ") == "report.pdf"


def test_sanitize_filename_keeps_unicode_names() -> None:
    assert AttachmentIntakePolicy.sanitize_filename("Договор №42.pdf") == "Договор №42.pdf"


def test_extension_check_is_case_insensitive() -> None:
    assert AttachmentIntakePolicy.extension_matches("application/pdf", "REPORT.PDF")


def test_extension_check_fails_closed_for_unsupported_media_type() -> None:
    assert not AttachmentIntakePolicy.extension_matches("application/x-msdownload", "setup.exe")


def test_allowed_alternative_extensions() -> None:
    assert _validate(filename="photo.jpeg", mime_type="image/jpeg").allowed
    assert _validate(filename="notes.md", mime_type="text/markdown").allowed
    assert _validate(filename="server.log", mime_type="text/plain").allowed


def test_blob_keys_are_uuid_only_and_derived_key_differs() -> None:
    attachment_id = uuid4()
    blob_key = AttachmentIntakePolicy.blob_key(attachment_id)
    derived_key = AttachmentIntakePolicy.derived_text_key(attachment_id)
    assert blob_key == f"attachments/{attachment_id}"
    assert derived_key != blob_key


def test_blob_key_never_leaks_filename_or_user() -> None:
    blob_key = AttachmentIntakePolicy.blob_key(uuid4())
    assert "invoice" not in blob_key
    assert "user" not in blob_key
    assert ".." not in blob_key


def test_attach_expiry_outlives_a_single_day() -> None:
    """Regression: a 24h attach TTL breaks follow-ups on a live thread."""
    expiry = AttachmentIntakePolicy.expiry_for("attach", now=_NOW)
    assert expiry - _NOW == timedelta(seconds=DEFAULT_ATTACHMENT_LIMITS.attach_ttl_seconds)
    assert expiry - _NOW > timedelta(days=1)


def test_index_expiry_uses_retention_window() -> None:
    expiry = AttachmentIntakePolicy.expiry_for("index", now=_NOW)
    assert (expiry - _NOW).days == DEFAULT_ATTACHMENT_LIMITS.index_retention_days


def test_expiry_is_timezone_aware_utc() -> None:
    assert AttachmentIntakePolicy.expiry_for("attach", now=_NOW).tzinfo is UTC


def test_default_expiry_uses_current_utc_clock() -> None:
    expiry = AttachmentIntakePolicy.expiry_for("attach")
    assert expiry.tzinfo is UTC
    assert expiry > datetime(2026, 1, 1, tzinfo=UTC)


def _attachment(*, expires_at: datetime | None) -> Attachment:
    """Minimal aggregate for retention checks (no I/O, no pipeline)."""
    attachment_id = uuid4()
    return Attachment(
        id=attachment_id,
        user_id="user-a",
        filename="invoice.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        blob_key=f"attachments/{attachment_id}",
        mode="attach",
        status="ready",
        created_at=_NOW,
        expires_at=expires_at,
    )


def test_row_inside_its_window_is_not_due() -> None:
    assert not AttachmentRetentionPolicy.is_due(_attachment(expires_at=_NOW + timedelta(seconds=60)), now=_NOW)


def test_row_at_the_exact_expiry_instant_is_due() -> None:
    """Boundary: ``expires_at`` is inclusive, so the TTL cannot be extended by a tick."""
    assert AttachmentRetentionPolicy.is_due(_attachment(expires_at=_NOW), now=_NOW)


def test_row_without_ttl_is_never_purged() -> None:
    """No TTL means the owner deletes it — retention must not guess."""
    assert not AttachmentRetentionPolicy.is_due(_attachment(expires_at=None), now=_NOW)


def test_naive_cutoff_is_refused_instead_of_compared() -> None:
    """Regression: a naive ``now`` would silently compare in local time (050)."""
    with pytest.raises(ValueError, match="timezone-aware"):
        AttachmentRetentionPolicy.is_due(_attachment(expires_at=_NOW), now=datetime(2026, 9, 25, 12, 0))


def test_model_expiry_property_uses_the_same_rule() -> None:
    """One rule, two callers: the property must not drift from the policy (010)."""
    assert _attachment(expires_at=_NOW - timedelta(seconds=1)).is_expired
    assert not _attachment(expires_at=_NOW + timedelta(days=1)).is_expired


def test_retention_sweep_batch_has_sane_bounds() -> None:
    assert DEFAULT_ATTACHMENT_LIMITS.retention_sweep_batch >= 1
    with pytest.raises(ValidationError):
        AttachmentLimits(retention_sweep_batch=0)
