# src/palatium_ai/domain/ports/document_parser.py

"""Port for turning untrusted bytes into page-addressed plain text (020).

``pages`` is the source of truth and ``text`` is computed from it, so page markers
used for citations can never drift from the page list (050).
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from palatium_ai.domain.attachments.parse_routing import ExtractionSource
from palatium_ai.domain.attachments.types import AttachmentRejectionReason


class DocumentParseError(ValueError):
    """Raised when untrusted bytes cannot be parsed into text.

    Domain-level so a corrupt or hostile file never surfaces as a driver
    exception (``PdfReadError``/``BadZipFile``) past the infrastructure boundary.
    """

    rejection_reason: AttachmentRejectionReason | None

    def __init__(self, message: str, *, rejection_reason: AttachmentRejectionReason | None = None) -> None:
        super().__init__(message)
        self.rejection_reason = rejection_reason


class ParsedPage(BaseModel):
    """One page/sheet/section of a parsed document, addressed for citations."""

    model_config = {"frozen": True}

    number: int = Field(ge=1)
    text: str


class ParsedDocument(BaseModel):
    """Parsed text; ``truncated`` records a hit cap instead of dropping text silently."""

    model_config = {"frozen": True}

    pages: tuple[ParsedPage, ...] = ()
    truncated: bool = False
    #: How text was obtained — audit/metrics; never trusted from the client.
    extraction_source: ExtractionSource = "none"
    #: Tesseract mean word confidence (0–100). ``None`` for Vision / non-OCR paths.
    ocr_mean_confidence: float | None = Field(default=None, ge=0.0, le=100.0)

    @property
    def page_count(self) -> int:
        """Number of parsed pages (0 for an empty document)."""
        return len(self.pages)

    @property
    def text(self) -> str:
        """Pages joined with ``[[page N]]`` markers so citations stay traceable."""
        return "\n\n".join(f"[[page {page.number}]]\n{page.text}" for page in self.pages)

    @property
    def flow_text(self) -> str:
        """Pages joined without markers, for security scanning.

        Page markers are attacker-influenceable seams: splitting a payload across
        a page boundary would otherwise break every injection pattern.
        """
        return "\n\n".join(page.text for page in self.pages)

    @property
    def total_chars(self) -> int:
        """Sum of page body lengths (no markers) for text-layer sufficiency checks."""
        return sum(len(page.text) for page in self.pages)


class DocumentParserPort(Protocol):
    """Async parser per media type; adapters run blocking libraries off the loop (050)."""

    def supports(self, mime_type: str) -> bool:
        """Whether this parser handles the media type (fail fast, no driver exception)."""
        ...

    async def parse(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
        """Extract page-addressed text from untrusted bytes."""
        ...
