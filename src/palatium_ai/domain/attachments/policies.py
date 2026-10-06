# src/palatium_ai/domain/attachments/policies.py

"""Intake policy for attachments: what may be stored, under which name and TTL (020).

Pure and deterministic — no I/O, no clock injection beyond an optional ``now``, so
every rule is unit-testable (055). Numeric limits are a value object; the media-type
registry is a closed domain constant, because widening it is a deliberate,
reviewable change, not a config tweak (070).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, Field

from .types import AttachmentMode, AttachmentRejectionReason

if TYPE_CHECKING:
    # Type-only: models.py imports this module for the expiry rule, so a runtime
    # import here would close a cycle (000 keeps the rule in one place anyway).
    from .models import Attachment

# Closed registry: declared MIME ↔ permitted file extensions. The allowlist is
# derived from these keys so the two can never drift apart (050).
_MEDIA_EXTENSIONS: dict[str, frozenset[str]] = {
    "application/pdf": frozenset({".pdf"}),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": frozenset({".docx"}),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": frozenset({".xlsx"}),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": frozenset({".pptx"}),
    "image/jpeg": frozenset({".jpg", ".jpeg"}),
    "image/png": frozenset({".png"}),
    "image/webp": frozenset({".webp"}),
    "text/csv": frozenset({".csv"}),
    "text/html": frozenset({".html", ".htm"}),
    "text/markdown": frozenset({".md"}),
    "text/plain": frozenset({".txt", ".log"}),
}

SUPPORTED_MEDIA_TYPES: frozenset[str] = frozenset(_MEDIA_EXTENSIONS)

# Characters that must never reach a stored filename or a log line.
_FORBIDDEN_FILENAME_CHARS = frozenset({"\x00", "\r", "\n"})


class AttachmentLimits(BaseModel):
    """Numeric intake limits; values come from AttachmentConfig in infrastructure wiring.

    Project-scoped KB (``mode=index`` + optional ``project_id``) will add per-project
    caps here when indexing storage ships (G09); not enforced in the W5 slice.
    """

    model_config = {"frozen": True}

    max_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1024, le=512 * 1024 * 1024)
    max_attachments_per_turn: int = Field(default=5, ge=1, le=50)
    max_filename_chars: int = Field(default=200, ge=16, le=255)
    presigned_url_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    # attach mode must outlive the thread, otherwise follow-up questions about an
    # earlier attachment fail while the dialog is still alive.
    attach_ttl_seconds: int = Field(default=7 * 24 * 3600, ge=300)
    index_retention_days: int = Field(default=365, ge=1, le=3650)
    #: Rows reclaimed per sweep pass. Bounded on purpose: an unbounded batch would
    #: turn one interactive request into an arbitrarily long delete loop (080).
    retention_sweep_batch: int = Field(default=200, ge=1, le=5000)
    #: Per-request body cap for ``POST /{id}/chunks/{index}`` (resumable upload).
    max_chunk_bytes: int = Field(default=8 * 1024 * 1024, ge=64 * 1024, le=64 * 1024 * 1024)


DEFAULT_ATTACHMENT_LIMITS = AttachmentLimits()


class IntakeDecision(BaseModel):
    """Outcome of intake validation: allowed or a typed refusal reason."""

    model_config = {"frozen": True}

    allowed: bool
    filename: str = Field(max_length=255)
    reason: AttachmentRejectionReason | None = None

    @property
    def refused(self) -> bool:
        """Convenience inverse of ``allowed`` for guard clauses."""
        return not self.allowed


class AttachmentIntakePolicy:
    """Pure gate for size, media type, filename safety and the per-thread quota."""

    @staticmethod
    def validate(
        *,
        filename: str,
        mime_type: str,
        size_bytes: int,
        limits: AttachmentLimits = DEFAULT_ATTACHMENT_LIMITS,
    ) -> IntakeDecision:
        """Validate the *file* properties of one upload before any blob or row exists.

        The quota axis is deliberately absent: it depends on a database count that
        must be read inside the same transaction that inserts the row, so a caller
        could otherwise treat a racy pre-read as authoritative (020).
        :meth:`quota_decision` owns that rule instead.
        """
        safe_name = AttachmentIntakePolicy.sanitize_filename(
            filename,
            max_chars=limits.max_filename_chars,
        )
        if not safe_name:
            return IntakeDecision(allowed=False, filename="", reason="filename_invalid")
        if size_bytes <= 0:
            return IntakeDecision(allowed=False, filename=safe_name, reason="size_invalid")
        if size_bytes > limits.max_size_bytes:
            return IntakeDecision(allowed=False, filename=safe_name, reason="size_exceeded")
        if mime_type not in SUPPORTED_MEDIA_TYPES:
            return IntakeDecision(allowed=False, filename=safe_name, reason="mime_not_allowed")
        if not AttachmentIntakePolicy.extension_matches(mime_type, safe_name):
            return IntakeDecision(allowed=False, filename=safe_name, reason="extension_mismatch")
        return IntakeDecision(allowed=True, filename=safe_name)

    @staticmethod
    def quota_decision(
        *,
        filename: str,
        in_flight: int,
        limits: AttachmentLimits = DEFAULT_ATTACHMENT_LIMITS,
    ) -> IntakeDecision:
        """Decide the quota axis from the thread's *in-flight* upload count.

        In-flight means rows still ``pending`` whose presigned ticket has not
        expired — uploads that are actually occupying a slot right now. Counting
        every row the thread ever created (including rejected and abandoned ones)
        locked a thread for the whole attachment TTL after a handful of attempts,
        so a legitimate message was refused as if it carried too many files.
        ``__init__`` is the sole writer of the threshold: the service maps a refusal
        from the repository through this policy so the typed reason has one home (010).
        """
        if in_flight >= limits.max_attachments_per_turn:
            return IntakeDecision(allowed=False, filename=filename, reason="turn_limit_exceeded")
        return IntakeDecision(allowed=True, filename=filename)

    @staticmethod
    def sanitize_filename(filename: str, *, max_chars: int = DEFAULT_ATTACHMENT_LIMITS.max_filename_chars) -> str:
        """Reduce a client-supplied name to a safe display name (no path, no controls)."""
        if any(char in _FORBIDDEN_FILENAME_CHARS for char in filename):
            return ""
        # Browsers send a bare name, but never trust it: drop any directory part.
        name = PurePosixPath(filename.replace("\\", "/")).name.strip()
        name = "".join(char for char in name if char.isprintable()).strip()
        # Collapse dot-only names, which are traversal markers rather than files.
        if not name or name.strip(".") == "":
            return ""
        if len(name) <= max_chars:
            return name
        return _truncate_keeping_suffix(name, max_chars=max_chars)

    @staticmethod
    def extension_matches(mime_type: str, filename: str) -> bool:
        """Cross-check the declared media type against the extension (defence in depth)."""
        allowed_extensions = _MEDIA_EXTENSIONS.get(mime_type)
        if allowed_extensions is None:
            return False
        suffix = PurePosixPath(filename).suffix.lower()
        return suffix in allowed_extensions

    @staticmethod
    def content_matches_declared(
        *,
        declared_mime: str,
        detected_mime: str | None,
        filename: str,
    ) -> IntakeDecision:
        """Refuse when magic-byte sniff disagrees with the intake declaration (020).

        ``detected_mime`` of ``None`` means sniff could not classify the payload:
        binary registry types fail closed; ``text/*`` declarations may proceed when
        the sniff returned the ambiguous ``text/*`` sentinel or nothing *only if*
        the declared type is already a text registry member (defence for UTF-8
        without a distinctive magic).
        """
        safe_name = AttachmentIntakePolicy.sanitize_filename(filename)
        if not safe_name:
            return IntakeDecision(allowed=False, filename="", reason="filename_invalid")
        declared = declared_mime.strip().lower()
        if declared not in SUPPORTED_MEDIA_TYPES:
            return IntakeDecision(allowed=False, filename=safe_name, reason="mime_not_allowed")

        detected = detected_mime.strip().lower() if detected_mime else None
        if detected is None:
            if declared.startswith("text/"):
                return IntakeDecision(allowed=True, filename=safe_name)
            return IntakeDecision(allowed=False, filename=safe_name, reason="mime_mismatch")

        if detected == "text/*":
            if declared.startswith("text/"):
                return IntakeDecision(allowed=True, filename=safe_name)
            return IntakeDecision(allowed=False, filename=safe_name, reason="mime_mismatch")

        if detected not in SUPPORTED_MEDIA_TYPES:
            return IntakeDecision(allowed=False, filename=safe_name, reason="mime_not_allowed")
        if detected != declared:
            return IntakeDecision(allowed=False, filename=safe_name, reason="mime_mismatch")
        if not AttachmentIntakePolicy.extension_matches(detected, safe_name):
            return IntakeDecision(allowed=False, filename=safe_name, reason="extension_mismatch")
        return IntakeDecision(allowed=True, filename=safe_name)

    @staticmethod
    def blob_key(attachment_id: UUID) -> str:
        """Content-addressed-by-id key: no filename, no user id, no traversal surface."""
        return f"attachments/{attachment_id}"

    @staticmethod
    def derived_text_key(attachment_id: UUID) -> str:
        """Where the parser writes extracted text (keeps the original blob intact)."""
        return f"attachments/{attachment_id}.text.json"

    @staticmethod
    def chunk_part_key(attachment_id: UUID, index: int) -> str:
        """Staging object for one resumable upload part (deleted after finalize)."""
        if index < 0:
            msg = "chunk index must be non-negative"
            raise ValueError(msg)
        return f"attachments/{attachment_id}/parts/{index}"

    @staticmethod
    def max_chunk_part_index(limits: AttachmentLimits = DEFAULT_ATTACHMENT_LIMITS) -> int:
        """Upper bound on part indices for retention cleanup (ceil(size/chunk))."""
        chunk = limits.max_chunk_bytes
        return (limits.max_size_bytes + chunk - 1) // chunk

    @staticmethod
    def expiry_for(
        mode: AttachmentMode,
        *,
        now: datetime | None = None,
        limits: AttachmentLimits = DEFAULT_ATTACHMENT_LIMITS,
    ) -> datetime:
        """Timezone-aware expiry: thread lifetime for attach, retention window for index."""
        reference = now or datetime.now(UTC)
        if mode == "index":
            return reference + timedelta(days=limits.index_retention_days)
        return reference + timedelta(seconds=limits.attach_ttl_seconds)


class AttachmentRetentionPolicy:
    """Pure retention rules: which rows a sweep may reclaim (020, 060).

    Kept deterministic and clock-injected: every row in one pass is judged against
    the same ``now``, because recomputing the clock per row could reclaim a row
    that is still inside its retention window (050).
    """

    @staticmethod
    def is_due(attachment: Attachment, *, now: datetime) -> bool:
        """True when the attachment's TTL has elapsed and its objects may be dropped."""
        _require_aware(now)
        if attachment.expires_at is None:
            # No TTL means "keep until the owner deletes it" — never an accidental purge.
            return False
        return attachment.expires_at <= now

    @staticmethod
    def is_stale_pending(attachment: Attachment, *, now: datetime, after_seconds: int) -> bool:
        """True when an upload that never completed can no longer legitimately complete.

        A ``pending`` row is minted together with a presigned PUT ticket. Once that
        ticket has expired the bytes can never arrive through the presigned path, so
        the row is dead weight: it must stop occupying a quota slot and it becomes
        reclaimable long before the row's own retention TTL elapses (020, 080).
        """
        _require_aware(now)
        if attachment.status != "pending":
            # Only an unfinished upload can be stale; a shorter TTL never revives it.
            return False
        return attachment.created_at + timedelta(seconds=after_seconds) <= now


def _require_aware(now: datetime) -> None:
    """Refuse a naive cutoff instead of comparing it in local time (050)."""
    if now.tzinfo is None or now.utcoffset() is None:
        msg = "retention cutoff must be timezone-aware (UTC)"
        raise ValueError(msg)


def _truncate_keeping_suffix(name: str, *, max_chars: int) -> str:
    """Shorten a name without orphaning its extension.

    A mangled suffix would silently change the media-type cross-check, so the
    extension is preserved and the stem absorbs the cut. When even the extension
    does not fit, the name is refused rather than stored misleadingly.
    """
    suffix = PurePosixPath(name).suffix
    budget = max_chars - len(suffix)
    if budget < 1:
        return ""
    return f"{name[:budget]}{suffix}"


__all__ = [
    "DEFAULT_ATTACHMENT_LIMITS",
    "SUPPORTED_MEDIA_TYPES",
    "AttachmentIntakePolicy",
    "AttachmentLimits",
    "AttachmentRetentionPolicy",
    "IntakeDecision",
]
