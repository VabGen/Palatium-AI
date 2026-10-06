# src/palatium_ai/domain/attachments/models.py

"""Attachment aggregate (000, 020): metadata row, never the bytes themselves.

Content lives in the blob store; the row carries identity, policy state and the
derived-artifact key. ``frozen`` keeps the aggregate immutable so updates go
through ``model_copy`` and can only be persisted by the repository port.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from .policies import AttachmentRetentionPolicy
from .types import AttachmentMode, AttachmentRejectionReason, AttachmentStatus

_TERMINAL_REFUSALS: frozenset[str] = frozenset({"rejected", "quarantined"})
_USABLE_STATUSES: frozenset[str] = frozenset({"ready", "indexed"})


class Attachment(BaseModel):
    """One uploaded attachment and its security lifecycle state."""

    model_config = {"frozen": True}

    id: UUID
    user_id: str = Field(min_length=1, max_length=128)
    thread_id: str | None = Field(default=None, max_length=128)
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=3, max_length=128)
    size_bytes: int = Field(ge=0)
    blob_key: str = Field(min_length=1, max_length=512)
    mode: AttachmentMode
    status: AttachmentStatus = "pending"
    page_count: int | None = Field(default=None, ge=0)
    derived_text_key: str | None = Field(default=None, max_length=512)
    rejection_reason: AttachmentRejectionReason | None = None
    error: str | None = Field(default=None, max_length=500)
    project_id: str | None = Field(default=None, max_length=64)
    #: Extracted-text PII classification (G06); mirrored from derived content on complete.
    contains_pii: bool = False
    created_at: datetime
    expires_at: datetime | None = None

    @field_validator("created_at", "expires_at")
    @classmethod
    def _timestamps_are_aware(cls, value: datetime | None) -> datetime | None:
        """Naive timestamps break TTL comparisons across processes (010, 050)."""
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            msg = "attachment timestamps must be timezone-aware (UTC)"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _refusals_carry_a_typed_reason(self) -> Attachment:
        """A refused attachment must state why — refusals are never anonymous."""
        if self.status in _TERMINAL_REFUSALS and self.rejection_reason is None:
            msg = "rejected/quarantined attachments require rejection_reason"
            raise ValueError(msg)
        return self

    @property
    def is_usable(self) -> bool:
        """True when the attachment may be referenced in a turn."""
        return self.status in _USABLE_STATUSES

    @property
    def is_expired(self) -> bool:
        """True when TTL elapsed; the rule itself lives in ``AttachmentRetentionPolicy`` (010)."""
        return AttachmentRetentionPolicy.is_due(self, now=datetime.now(UTC))


__all__ = ["Attachment"]
