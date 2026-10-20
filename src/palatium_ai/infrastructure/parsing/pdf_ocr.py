# src/palatium_ai/infrastructure/parsing/pdf_ocr.py

"""Optional scanned-PDF OCR via PyMuPDF rasterize + Tesseract (optional extras).

Local OCR is CPU-bound and runs on untrusted rasters, so both dimensions are
bounded explicitly (080): one Tesseract child per invocation has a hard timeout,
and one document has a wall-clock budget. Without them a single pathological page
kept the subprocess (and the ``POST /complete`` request behind it) alive forever.
"""

from __future__ import annotations

import asyncio
import time

from typing import TYPE_CHECKING, Any

import structlog

from palatium_ai.domain.ports.document_parser import (
    DocumentParseError,
    ParsedDocument,
    ParsedPage,
)

if TYPE_CHECKING:
    from asyncio import Semaphore

logger = structlog.get_logger(__name__)

_PDF_MIME = "application/pdf"


class TesseractPdfOcrParser:
    """Rasterize PDF pages (fitz) and OCR them when the text layer is empty."""

    def __init__(
        self,
        *,
        max_chars: int,
        max_pages: int,
        timeout_seconds: float,
        budget_seconds: float,
        limiter: Semaphore,
        lang: str = "eng+rus",
        dpi: int = 150,
        tesseract_cmd: str | None = None,
    ) -> None:
        self._max_chars = max_chars
        self._max_pages = max_pages
        self._timeout_seconds = timeout_seconds
        self._budget_seconds = budget_seconds
        self._limiter = limiter
        self._lang = lang
        self._dpi = dpi
        self._tesseract_cmd = (tesseract_cmd or "").strip() or None

    def supports(self, mime_type: str) -> bool:
        """Only ``application/pdf``."""
        return mime_type == _PDF_MIME

    async def parse(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
        """OCR off the loop; missing pymupdf/pytesseract → typed error."""
        _ = mime_type, filename
        # One OCR slot per process: parallel uploads must queue, not multiply the
        # CPU demand until every request misses its own budget.
        async with self._limiter:
            return await asyncio.to_thread(self._parse_sync, data)

    def _parse_sync(self, data: bytes) -> ParsedDocument:
        try:
            import fitz
            import pytesseract

            from PIL import Image
        except ImportError as exc:
            msg = "pdf OCR extras missing; install pymupdf, Pillow and pytesseract"
            raise DocumentParseError(msg) from exc

        if self._tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self._tesseract_cmd

        try:
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise DocumentParseError("pdf is corrupt or not a pdf") from exc

        try:
            pages, truncated = self._ocr_pages(fitz, pytesseract, Image, doc)
        finally:
            doc.close()

        if not any(page.text.strip() for page in pages):
            raise DocumentParseError("pdf OCR produced no text")

        return ParsedDocument(
            pages=tuple(pages),
            truncated=truncated,
            extraction_source="ocr",
        )

    def _ocr_pages(
        self,
        fitz: Any,
        pytesseract: Any,
        image_factory: Any,
        doc: Any,
    ) -> tuple[list[ParsedPage], bool]:
        """Rasterize + OCR until the page cap, the char cap or the document budget."""
        pages: list[ParsedPage] = []
        truncated = False
        total_chars = 0
        deadline = time.monotonic() + self._budget_seconds
        scale = self._dpi / 72.0
        matrix = fitz.Matrix(scale, scale)
        page_count = min(doc.page_count, self._max_pages)
        if doc.page_count > self._max_pages:
            truncated = True
        for index in range(page_count):
            if time.monotonic() >= deadline:
                logger.warning(
                    "pdf OCR budget exhausted; remaining pages skipped",
                    page=index + 1,
                    pages=page_count,
                    budget_seconds=self._budget_seconds,
                )
                truncated = True
                break
            page = doc.load_page(index)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image = image_factory.frombytes("RGB", (pix.width, pix.height), pix.samples)
            text = self._page_text(pytesseract, image, index=index, page_count=page_count)
            if text is None:
                truncated = True
                break
            budget = self._max_chars - total_chars
            if len(text) > budget:
                text = text[: max(0, budget)]
                truncated = True
            total_chars += len(text)
            pages.append(ParsedPage(number=index + 1, text=text))
            if total_chars >= self._max_chars:
                truncated = True
                break
        return pages, truncated

    def _page_text(self, pytesseract: Any, image: Any, *, index: int, page_count: int) -> str | None:
        """OCR one page; ``None`` means "stop the document" (the child timed out)."""
        try:
            return str(
                pytesseract.image_to_string(
                    image,
                    lang=self._lang,
                    timeout=self._timeout_seconds,
                )
            ).strip()
        except RuntimeError as exc:
            # pytesseract raises a bare RuntimeError on ``subprocess`` timeout and
            # has already killed the child. Stop here: the next page would burn the
            # same budget, and Vision escalation is the better answer (055).
            if "timeout" in str(exc).lower():
                logger.warning(
                    "pdf page OCR timed out; document OCR stopped",
                    page=index + 1,
                    pages=page_count,
                    timeout_seconds=self._timeout_seconds,
                )
                return None
            logger.warning("pdf page OCR failed", page=index + 1, error_type=type(exc).__name__)
            return ""
        except Exception as exc:  # noqa: BLE001  # one unreadable page must not fail the whole document (035)
            logger.warning("pdf page OCR failed", page=index + 1, error_type=type(exc).__name__)
            return ""


__all__ = ["TesseractPdfOcrParser"]
