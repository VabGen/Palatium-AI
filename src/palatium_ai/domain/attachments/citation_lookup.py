# src/palatium_ai/domain/attachments/citation_lookup.py

"""One bounded slice of attachment text around a citation (W3b-2).

The response is a *window*, not the document: attaching the whole body to every
citation click would turn a reading aid into a download path that bypasses
``issue_download`` and its presigned URL (020). ``total_chars`` tells the UI how much
of the source it is not seeing, so the fragment never pretends to be the file.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from palatium_ai.domain.content.citations.locate import CitationLocateOutcome

#: ``masked`` means the stored body was redacted at intake (injection spans or PII),
#: so the user is reading an edited view — the UI must say so.
CitationTextState = Literal["full", "masked"]


class AttachmentCitationLookup(BaseModel):
    """Where a cited quote sits inside the attachment text we sent to the model."""

    model_config = {"frozen": True}

    attachment_id: UUID
    filename: str
    outcome: CitationLocateOutcome
    #: Absolute offsets in the stored text; ``None`` when nothing is highlighted.
    start: int | None = None
    end: int | None = None
    window_start: int = Field(ge=0)
    window_end: int = Field(ge=0)
    text: str
    total_chars: int = Field(ge=0)
    text_state: CitationTextState = "full"

    @model_validator(mode="after")
    def _window_is_consistent(self) -> AttachmentCitationLookup:
        if self.window_end < self.window_start or self.window_end > self.total_chars:
            raise ValueError("window must satisfy 0 <= window_start <= window_end <= total_chars")
        if (self.start is None) != (self.end is None):
            raise ValueError("citation slice needs start and end together")
        return self


__all__ = ["AttachmentCitationLookup", "CitationTextState"]
