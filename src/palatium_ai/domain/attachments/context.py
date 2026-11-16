# src/palatium_ai/domain/attachments/context.py

"""Turn-scoped, already-fenced attachment blocks (020, 065).

Crossing into a prompt is an explicit, typed act: a block exists only after the
service re-checked the stored content and wrapped it with
``wrap_untrusted_tool_output``. Nothing in the dialog path concatenates raw
attachment text on its own, so the fence cannot be forgotten by a later caller.

Level 0 of the attachment pipeline: the block carries the metadata the selection
and presentation stages need (kind, text availability, page count) instead of
asking them to re-derive it from prompt text. ``text_state`` is the contract for
"the file is attached but OCR/extraction produced nothing" — a worker must not
turn that into a greeting (020, 055).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.types import AttachmentKind, UntrustedContentAction

#: Whether the fenced body carries extracted text or only the read-on-demand notice.
AttachmentTextState = Literal["extracted", "missing"]

_IMAGE_PREFIX = "image/"
#: Everything that is not an image is a document for selection purposes. The
#: mime registry for parsing lives elsewhere; this is only the modality filter.
_DOCUMENT_HINTS = (
    "pdf",
    "word",
    "officedocument",
    "excel",
    "spreadsheet",
    "text/",
    "csv",
    "rtf",
)


class AttachmentContextBlock(BaseModel):
    """One fenced attachment ready to be appended to a turn's context."""

    model_config = {"frozen": True}

    attachment_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    source: str = Field(min_length=1, max_length=128)
    fenced_text: str
    action: UntrustedContentAction
    page_count: int = Field(default=0, ge=0)
    #: Upload mime; defaults keep old fixtures/callers valid (never guessed at runtime).
    mime_type: str = Field(default="application/octet-stream", min_length=3, max_length=128)
    #: ``missing`` means the upload is usable but no text was extracted (OCR failed or
    #: still pending): the fenced body is the read-on-demand notice, not content.
    text_state: AttachmentTextState = "extracted"
    #: PII classification of the row. It travels with the block so the vision gate can
    #: decide (and audit) without re-reading the row, while the fence body stays text-only.
    contains_pii: bool = False

    @property
    def is_image(self) -> bool:
        return self.mime_type.strip().casefold().startswith(_IMAGE_PREFIX)

    @property
    def has_usable_text(self) -> bool:
        """True when the model can read the document body from this fence."""
        return self.text_state == "extracted" and bool(self.fenced_text.strip())

    def matches_kind(self, kind: AttachmentKind) -> bool:
        """Modality filter for the ask; ``any`` never filters."""
        if kind == "any":
            return True
        return self.is_image if kind == "image" else not self.is_image


class AttachmentTurnContext(BaseModel):
    """Ordered blocks resolved for one dialog turn."""

    model_config = {"frozen": True}

    blocks: tuple[AttachmentContextBlock, ...] = ()

    @property
    def fenced_text(self) -> str:
        """Blocks joined for a single context slot; empty when nothing was attached."""
        return "\n\n".join(block.fenced_text for block in self.blocks)

    @property
    def attachment_ids(self) -> tuple[UUID, ...]:
        """Ids of the attachments that actually made it into the turn."""
        return tuple(block.attachment_id for block in self.blocks)

    @property
    def has_usable_text(self) -> bool:
        """True when at least one selected file can be read (Level 0 flag)."""
        return any(block.has_usable_text for block in self.blocks)

    @property
    def all_text_missing(self) -> bool:
        """Every attached file is attached-but-unreadable (honest-failure signal)."""
        return bool(self.blocks) and not self.has_usable_text


def mime_kind(mime_type: str) -> Literal["image", "document"]:
    """Map a mime type to the selection modality (closed vocabulary)."""
    lowered = (mime_type or "").strip().casefold()
    if lowered.startswith(_IMAGE_PREFIX):
        return "image"
    return "document"


def is_document_mime(mime_type: str) -> bool:
    """True for mime types the document path is expected to handle."""
    lowered = (mime_type or "").strip().casefold()
    return any(hint in lowered for hint in _DOCUMENT_HINTS)


__all__ = [
    "AttachmentContextBlock",
    "AttachmentTextState",
    "AttachmentTurnContext",
    "is_document_mime",
    "mime_kind",
]
