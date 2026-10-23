# src/palatium_ai/infrastructure/parsing/pdf_ocr.py

"""Optional scanned-PDF OCR via PyMuPDF rasterize + Tesseract (optional extras).

Local OCR is CPU-bound and runs on untrusted rasters, so every dimension is bounded
explicitly (080): one Tesseract child per page has a hard timeout, one document has a
wall-clock budget, and the number of concurrent children is capped by a process-wide
semaphore.

Pages are OCR-ed **concurrently**, bounded by that semaphore. Sequential pages were the
observed bottleneck: a 10-page scan spent ~2.7 min even though
``ATTACHMENTS_OCR_MAX_CONCURRENCY`` only ever bounded *documents*, so one upload could
never use more than one slot. Each page now renders and OCRs in its own worker thread
over its **own** ``fitz.Document`` (PyMuPDF objects are not thread-safe), which keeps
peak memory proportional to the concurrency cap rather than to the page count.

A timed-out page yields an empty page instead of stopping the document, so the router
can escalate exactly that page to Vision and keep the rest of the OCR text.
"""

from __future__ import annotations

import asyncio
import time

from collections.abc import Sequence
from dataclasses import dataclass
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

# Two page timeouts in one document say the raster/engine pairing is wrong (not one
# pathological page), so the rest is deferred to the page-level Vision fallback instead
# of burning the whole OCR budget on identical kills. Concurrent page tasks share the
# counter; a lost update costs one extra attempt and nothing else.
_MAX_PAGE_TIMEOUTS = 2


@dataclass(frozen=True, slots=True)
class _Extras:
    """Imported OCR stack plus the render matrix — resolved once per document."""

    fitz: Any
    pytesseract: Any
    image_factory: Any
    matrix: Any


@dataclass(slots=True)
class _Run:
    """Per-document OCR state shared by the concurrent page tasks (one event loop)."""

    deadline: float
    page_count: int
    timeouts: int = 0
    budget_logged: bool = False

    def page_timeout(self, configured: float) -> float:
        """Configured per-page kill, capped by the document's remaining budget."""
        return min(configured, self.deadline - time.monotonic())


@dataclass(frozen=True, slots=True)
class _PageOcr:
    """One page outcome: text, or why it has none."""

    number: int
    text: str = ""
    timed_out: bool = False
    skipped: bool = False


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
        run = _Run(
            deadline=time.monotonic() + self._budget_seconds,
            page_count=0,
        )
        extras, page_count = await asyncio.to_thread(self._inspect, data)
        run.page_count = min(page_count, self._max_pages)
        results = await asyncio.gather(
            *(self._ocr_page(extras, data, index=index, run=run) for index in range(run.page_count)),
        )
        pages, truncated = self._assemble(results, page_count=page_count)
        if not any(page.text.strip() for page in pages):
            raise DocumentParseError("pdf OCR produced no text")
        return ParsedDocument(
            pages=tuple(pages),
            truncated=truncated,
            extraction_source="ocr",
        )

    def _inspect(self, data: bytes) -> tuple[_Extras, int]:
        """Import the OCR stack and read the page count in one worker thread."""
        try:
            import fitz
            import pytesseract

            from PIL import Image
        except ImportError as exc:
            msg = "pdf OCR extras missing; install pymupdf, Pillow and pytesseract"
            raise DocumentParseError(msg) from exc

        if self._tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self._tesseract_cmd

        scale = self._dpi / 72.0
        extras = _Extras(
            fitz=fitz,
            pytesseract=pytesseract,
            image_factory=Image,
            matrix=fitz.Matrix(scale, scale),
        )
        try:
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise DocumentParseError("pdf is corrupt or not a pdf") from exc
        try:
            return extras, int(doc.page_count)
        finally:
            doc.close()

    async def _ocr_page(self, extras: _Extras, data: bytes, *, index: int, run: _Run) -> _PageOcr:
        """OCR one page inside an OCR slot; never raises for a single bad page (035)."""
        number = index + 1
        async with self._limiter:
            if run.timeouts >= _MAX_PAGE_TIMEOUTS:
                return _PageOcr(number=number, skipped=True)
            timeout = run.page_timeout(self._timeout_seconds)
            if timeout <= 0.0:
                if not run.budget_logged:
                    run.budget_logged = True
                    logger.warning(
                        "pdf OCR budget exhausted; remaining pages skipped",
                        page=number,
                        pages=run.page_count,
                        budget_seconds=self._budget_seconds,
                    )
                return _PageOcr(number=number, skipped=True)
            text = await asyncio.to_thread(self._page_text, extras, data, index=index, timeout=timeout)
        if text is None:
            run.timeouts += 1
            if run.timeouts == _MAX_PAGE_TIMEOUTS:
                logger.warning(
                    "pdf pages OCR timed out; remaining pages deferred to vision",
                    page=number,
                    pages=run.page_count,
                    timeout_seconds=self._timeout_seconds,
                )
            return _PageOcr(number=number, timed_out=True)
        return _PageOcr(number=number, text=text)

    def _page_text(self, extras: _Extras, data: bytes, *, index: int, timeout: float) -> str | None:
        """Render + OCR one page in this thread; ``None`` means "timed out" → Vision."""
        try:
            # A fresh Document per page: one shared instance is not safe across the
            # concurrent workers, and xref parsing is negligible next to OCR itself.
            doc = extras.fitz.open(stream=data, filetype="pdf")
        except Exception as exc:  # noqa: BLE001  # fitz raises its own types; one page must not fail the document (035)
            logger.warning("pdf page render failed", page=index + 1, error_type=type(exc).__name__)
            return ""
        try:
            pix = doc.load_page(index).get_pixmap(matrix=extras.matrix, alpha=False)
            image = extras.image_factory.frombytes("RGB", (pix.width, pix.height), pix.samples)
        except Exception as exc:  # noqa: BLE001  # one unreadable page must not fail the whole document (035)
            logger.warning("pdf page render failed", page=index + 1, error_type=type(exc).__name__)
            return ""
        finally:
            doc.close()

        try:
            return str(
                extras.pytesseract.image_to_string(
                    image,
                    lang=self._lang,
                    timeout=timeout,
                )
            ).strip()
        except RuntimeError as exc:
            # pytesseract raises a bare RuntimeError on ``subprocess`` timeout and
            # has already killed the child. The page is empty for OCR but the rest of
            # the document is still worth reading; Vision covers this page alone (055).
            if "timeout" in str(exc).lower():
                logger.warning(
                    "pdf page OCR timed out; page deferred to vision",
                    page=index + 1,
                    timeout_seconds=timeout,
                )
                return None
            logger.warning("pdf page OCR failed", page=index + 1, error_type=type(exc).__name__)
            return ""
        except Exception as exc:  # noqa: BLE001  # one unreadable page must not fail the whole document (035)
            logger.warning("pdf page OCR failed", page=index + 1, error_type=type(exc).__name__)
            return ""

    def _assemble(
        self,
        results: Sequence[_PageOcr],
        *,
        page_count: int,
    ) -> tuple[list[ParsedPage], bool]:
        """Apply the page/char caps in page order, after the concurrent OCR finished.

        Character budget is applied here rather than in the workers so the cut stays
        deterministic: page 5 cannot win the budget just by finishing first.
        """
        truncated = page_count > self._max_pages
        pages: list[ParsedPage] = []
        total_chars = 0
        for result in results:
            if result.skipped:
                truncated = True
                break
            if result.timed_out:
                truncated = True
            budget = self._max_chars - total_chars
            text = result.text
            if len(text) > budget:
                text = text[: max(0, budget)]
                truncated = True
            total_chars += len(text)
            pages.append(ParsedPage(number=result.number, text=text))
            if total_chars >= self._max_chars:
                truncated = True
                break
        return pages, truncated


__all__ = ["TesseractPdfOcrParser"]
