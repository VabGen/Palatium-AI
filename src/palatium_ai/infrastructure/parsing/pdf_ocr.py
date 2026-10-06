# src/palatium_ai/infrastructure/parsing/pdf_ocr.py

"""Optional scanned-PDF OCR via PyMuPDF rasterize + Tesseract (optional extras)."""

from __future__ import annotations

import asyncio

import structlog

from palatium_ai.domain.ports.document_parser import (
    DocumentParseError,
    ParsedDocument,
    ParsedPage,
)

logger = structlog.get_logger(__name__)

_PDF_MIME = "application/pdf"


class TesseractPdfOcrParser:
    """Rasterize PDF pages (fitz) and OCR them when the text layer is empty."""

    def __init__(
        self,
        *,
        max_chars: int,
        max_pages: int,
        lang: str = "eng+rus",
        dpi: int = 150,
        tesseract_cmd: str | None = None,
    ) -> None:
        self._max_chars = max_chars
        self._max_pages = max_pages
        self._lang = lang
        self._dpi = dpi
        self._tesseract_cmd = (tesseract_cmd or "").strip() or None

    def supports(self, mime_type: str) -> bool:
        """Only ``application/pdf``."""
        return mime_type == _PDF_MIME

    async def parse(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
        """OCR off the loop; missing pymupdf/pytesseract → typed error."""
        _ = mime_type, filename
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

        pages: list[ParsedPage] = []
        truncated = False
        total_chars = 0
        scale = self._dpi / 72.0
        matrix = fitz.Matrix(scale, scale)
        try:
            page_count = min(doc.page_count, self._max_pages)
            if doc.page_count > self._max_pages:
                truncated = True
            for index in range(page_count):
                page = doc.load_page(index)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                try:
                    text = pytesseract.image_to_string(image, lang=self._lang).strip()
                except Exception as exc:
                    logger.warning("pdf page OCR failed", page=index + 1, error_type=type(exc).__name__)
                    text = ""
                budget = self._max_chars - total_chars
                if len(text) > budget:
                    text = text[: max(0, budget)]
                    truncated = True
                total_chars += len(text)
                pages.append(ParsedPage(number=index + 1, text=text))
                if total_chars >= self._max_chars:
                    truncated = True
                    break
        finally:
            doc.close()

        if not any(page.text.strip() for page in pages):
            raise DocumentParseError("pdf OCR produced no text")

        return ParsedDocument(
            pages=tuple(pages),
            truncated=truncated,
            extraction_source="ocr",
        )


__all__ = ["TesseractPdfOcrParser"]
