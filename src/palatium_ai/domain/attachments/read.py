# src/palatium_ai/domain/attachments/read.py

"""On-demand attachment read contracts (070 ``platform.read_attachment``).

Cached text lives in the derived blob (``AttachmentContent``); row columns
``ocr_applied`` / ``extract_status`` / ``extracted_chars`` are extraction
*metadata* for observability and reingest filters — not a second text SoT.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

#: How the body was obtained for this read (parser cascade outcome).
OcrEngine = Literal["tesseract", "llm_vision"]

#: Row-level extraction state (nullable in DB; closed vocabulary when set).
ExtractStatus = Literal["text_ok", "ocr_ok", "vision_ok", "empty"]

#: Default slice ceiling for a single tool response (065 token budget).
DEFAULT_READ_MAX_CHARS = 32_000


class AttachmentReadRequest(BaseModel):
    """Owner-scoped read of one attachment (020 RBAC via ``user_id``)."""

    model_config = {"frozen": True}

    attachment_id: UUID
    user_id: str = Field(min_length=1, max_length=128)
    max_chars: int = Field(default=DEFAULT_READ_MAX_CHARS, ge=1, le=500_000)
    offset: int = Field(default=0, ge=0)
    #: Bypass derived-text cache and re-run ``DocumentParserPort.parse``.
    force_ocr: bool = False


class AttachmentReadResult(BaseModel):
    """Sliced attachment text plus extraction telemetry for the agent."""

    model_config = {"frozen": True}

    attachment_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=3, max_length=128)
    text: str = ""
    truncated: bool = False
    offset: int = Field(default=0, ge=0)
    total_chars: int = Field(default=0, ge=0)
    #: True when this call ran parser/OCR (not a pure cache hit).
    ocr_applied: bool = False
    #: True when text came from an existing non-empty derived blob.
    ocr_cached: bool = False
    ocr_engine: OcrEngine | None = None
    extract_status: ExtractStatus | None = None
    #: Soft degradation when both Tesseract and Vision yield nothing (035).
    notice: str | None = Field(default=None, max_length=1_000)


def extraction_source_to_ocr_engine(source: str | None) -> OcrEngine | None:
    """Map ``ParsedDocument.extraction_source`` to tool/metric ``ocr_engine``."""
    if source == "ocr":
        return "tesseract"
    if source == "vision":
        return "llm_vision"
    return None


def extraction_source_to_extract_status(
    source: str | None,
    *,
    text_chars: int,
) -> ExtractStatus:
    """Derive row ``extract_status`` from parser source and usable length."""
    if text_chars <= 0:
        return "empty"
    if source == "vision":
        return "vision_ok"
    if source == "ocr":
        return "ocr_ok"
    return "text_ok"


__all__ = [
    "DEFAULT_READ_MAX_CHARS",
    "AttachmentReadRequest",
    "AttachmentReadResult",
    "ExtractStatus",
    "OcrEngine",
    "extraction_source_to_extract_status",
    "extraction_source_to_ocr_engine",
]
