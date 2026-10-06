# src/palatium_ai/domain/attachments/errors.py

"""Typed attachment errors (030.8, 035): use-cases never leak driver exceptions.

Presentation maps these to HTTP codes and, crucially, to a *reason the user can
act on* (too big, wrong type, quarantine) without exposing internals. A refusal
is always typed, never a free-text ``str(exc)`` from a driver.
"""

from __future__ import annotations

from uuid import UUID

from palatium_ai.core.exceptions import PalatiumError
from palatium_ai.domain.attachments.types import AttachmentRejectionReason


class AttachmentError(PalatiumError):
    """Base class for attachment use-case failures."""


class AttachmentIntakeRejectedError(AttachmentError):
    """Intake policy refused the upload before any object or row was created."""

    def __init__(self, reason: AttachmentRejectionReason, *, filename: str = "") -> None:
        self.reason = reason
        self.filename = filename
        message = f"attachment intake refused ({reason})"
        if filename:
            message = f"attachment {filename!r} refused ({reason})"
        super().__init__(message)


class AttachmentUploadTooLargeError(AttachmentError):
    """A proxied upload body is bigger than the configured intake cap (020).

    Deliberately not an :class:`AttachmentIntakeRejectedError`: the bytes are
    already in flight by the time this is detected, so presentation answers
    ``413`` instead of a ``400`` that would suggest fixing the metadata.
    """

    def __init__(self, attachment_id: UUID, *, size_bytes: int, max_size_bytes: int) -> None:
        self.attachment_id = attachment_id
        self.size_bytes = size_bytes
        self.max_size_bytes = max_size_bytes
        super().__init__(f"attachment {attachment_id} upload is {size_bytes} bytes, over the {max_size_bytes} byte cap")


class AttachmentNotFoundError(AttachmentError):
    """No attachment visible to the acting user for the given id (060)."""

    def __init__(self, attachment_id: UUID) -> None:
        self.attachment_id = attachment_id
        super().__init__(f"attachment not found: {attachment_id}")


class AttachmentNotUsableError(AttachmentError):
    """The attachment exists but is not in a state that may enter a turn (020)."""

    def __init__(self, attachment_id: UUID, *, state: str) -> None:
        self.attachment_id = attachment_id
        self.state = state
        super().__init__(f"attachment {attachment_id} is not usable (state={state})")


class AttachmentModeMismatchError(AttachmentError):
    """The requested operation does not match the attachment's declared mode."""

    def __init__(self, attachment_id: UUID, *, expected: str, actual: str) -> None:
        self.attachment_id = attachment_id
        self.expected = expected
        self.actual = actual
        super().__init__(f"attachment {attachment_id} mode is {actual}, expected {expected}")


class AttachmentContentMissingError(AttachmentError):
    """Derived content is absent even though the row claims a ready state.

    This is a data-integrity failure, so it must surface loudly instead of
    silently degrading to an attachment with no body.
    """

    def __init__(self, attachment_id: UUID) -> None:
        self.attachment_id = attachment_id
        super().__init__(f"derived content missing for attachment {attachment_id}")


__all__ = [
    "AttachmentContentMissingError",
    "AttachmentError",
    "AttachmentIntakeRejectedError",
    "AttachmentModeMismatchError",
    "AttachmentNotFoundError",
    "AttachmentNotUsableError",
    "AttachmentUploadTooLargeError",
]
