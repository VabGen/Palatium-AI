# src/palatium_ai/infrastructure/parsing/routed_parser.py

"""MIME + text-layer routing wrapper around leaf parsers (domain parse_routing)."""

from __future__ import annotations

import asyncio

from typing import TYPE_CHECKING, Protocol, cast

import structlog

from palatium_ai.domain.attachments.parse_routing import (
    DEFAULT_MIN_AVG_CHARS_PER_PAGE,
    DEFAULT_OCR_MIN_CHARS,
    DEFAULT_OCR_MIN_CONFIDENCE,
    DEFAULT_OCR_MIN_PRINTABLE_RATIO,
    choose_parse_strategy,
    ocr_text_is_usable,
    text_layer_is_sufficient,
)
from palatium_ai.domain.ports.document_parser import DocumentParseError, ParsedDocument, ParsedPage

if TYPE_CHECKING:
    from palatium_ai.domain.ports.document_parser import DocumentParserPort

logger = structlog.get_logger(__name__)


class _PdfFigureEnricher(Protocol):
    """Optional VLM figure pass for text-layer PDFs (G14)."""

    async def enrich_figures(self, data: bytes, base: ParsedDocument) -> ParsedDocument: ...


class _PageVision(Protocol):
    """Optional per-page VLM pass used when only some OCR pages failed (055)."""

    async def parse_pages(
        self,
        data: bytes,
        *,
        page_numbers: tuple[int, ...],
    ) -> ParsedDocument: ...


class RoutedDocumentParser:
    """Apply ``choose_parse_strategy`` after PDF text-layer extract; images stay leaf."""

    def __init__(
        self,
        *,
        inner: DocumentParserPort,
        model_supports_vision: bool,
        parse_timeout_seconds: float,
        pdf_ocr: DocumentParserPort | None = None,
        pdf_vision: DocumentParserPort | None = None,
        figure_enricher: _PdfFigureEnricher | None = None,
        min_avg_chars_per_page: int = DEFAULT_MIN_AVG_CHARS_PER_PAGE,
        ocr_min_chars: int = DEFAULT_OCR_MIN_CHARS,
        ocr_min_printable_ratio: float = DEFAULT_OCR_MIN_PRINTABLE_RATIO,
        ocr_min_confidence: float = DEFAULT_OCR_MIN_CONFIDENCE,
    ) -> None:
        self._inner = inner
        self._model_supports_vision = model_supports_vision
        self._parse_timeout_seconds = parse_timeout_seconds
        self._pdf_ocr = pdf_ocr
        self._pdf_vision = pdf_vision
        self._figure_enricher = figure_enricher
        self._min_avg_chars = min_avg_chars_per_page
        self._ocr_min_chars = ocr_min_chars
        self._ocr_min_printable_ratio = ocr_min_printable_ratio
        self._ocr_min_confidence = ocr_min_confidence

    def supports(self, mime_type: str) -> bool:
        """Delegate capability to the leaf composite (intake gate)."""
        return self._inner.supports(mime_type)

    async def parse(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
        """Parse under one wall-clock budget; overrun is a typed refusal (030.8).

        Every upload is a synchronous ``POST /complete``: an unbounded stage would
        hold the request (and the client's chip) open forever. The budget is the
        last line of defence behind the per-call OCR/Vision timeouts.
        """
        try:
            async with asyncio.timeout(self._parse_timeout_seconds):
                return await self._route(data, mime_type=mime_type, filename=filename)
        except TimeoutError as exc:
            logger.warning(
                "document parse exceeded its budget",
                mime_type=mime_type,
                budget_seconds=self._parse_timeout_seconds,
            )
            msg = "document parse exceeded the configured time budget"
            raise DocumentParseError(msg) from exc

    async def _route(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
        """Parse, then for PDF re-route when the text layer is empty/sparse."""
        decision = choose_parse_strategy(
            mime_type=mime_type,
            model_supports_vision=self._model_supports_vision,
        )
        if decision.strategy == "refuse":
            raise DocumentParseError(f"unsupported media type for parse routing: {mime_type}")

        if mime_type != "application/pdf":
            return await self._inner.parse(data, mime_type=mime_type, filename=filename)

        # PDF: always probe text layer first (cheap), then decide.
        probed = await self._inner.parse(data, mime_type=mime_type, filename=filename)
        if text_layer_is_sufficient(
            total_chars=probed.total_chars,
            page_count=max(probed.page_count, 1),
            min_avg_chars_per_page=self._min_avg_chars,
        ):
            base = probed.model_copy(update={"extraction_source": "text_layer"})
            if self._figure_enricher is not None:
                try:
                    return await self._figure_enricher.enrich_figures(data, base)
                except DocumentParseError as exc:
                    logger.warning(
                        "pdf figure enrichment failed; keeping text layer",
                        error_type=type(exc).__name__,
                    )
                    return base
            return base

        after = choose_parse_strategy(
            mime_type=mime_type,
            model_supports_vision=self._model_supports_vision,
            text_layer_chars=probed.total_chars,
            page_count=max(probed.page_count, 1),
            min_avg_chars_per_page=self._min_avg_chars,
        )
        logger.info(
            "pdf text layer insufficient; routing",
            strategy=after.strategy,
            reason=after.reason,
            total_chars=probed.total_chars,
            pages=probed.page_count,
        )
        return await self._progressive_pdf_scan(
            data,
            mime_type=mime_type,
            filename=filename,
            page_count=max(probed.page_count, 1),
        )

    async def _progressive_pdf_scan(
        self,
        data: bytes,
        *,
        mime_type: str,
        filename: str,
        page_count: int,
    ) -> ParsedDocument:
        """Tesseract OCR first; escalate page-by-page, then document-wide (2026)."""
        ocr_doc: ParsedDocument | None = None
        if self._pdf_ocr is not None:
            try:
                ocr_doc = await self._pdf_ocr.parse(data, mime_type=mime_type, filename=filename)
                ocr_doc = await self._recover_failed_pages(data, ocr_doc, page_count=page_count)
                if self._ocr_is_usable(ocr_doc):
                    return ocr_doc
                logger.info(
                    "pdf OCR quality insufficient; escalating to vision",
                    chars=len(ocr_doc.flow_text.strip()),
                    mean_confidence=ocr_doc.ocr_mean_confidence,
                )
            except DocumentParseError as exc:
                logger.warning(
                    "pdf OCR failed; escalating to vision if available",
                    error_type=type(exc).__name__,
                )

        if self._pdf_vision is not None:
            try:
                return await self._pdf_vision.parse(data, mime_type=mime_type, filename=filename)
            except DocumentParseError:
                if ocr_doc is not None:
                    return ocr_doc
                raise

        if ocr_doc is not None:
            return ocr_doc
        msg = "pdf has no usable text layer and OCR/vision fallback is unavailable"
        raise DocumentParseError(msg)

    def _ocr_is_usable(self, doc: ParsedDocument) -> bool:
        """Whole-document quality gate (060 progressive escalation, unchanged)."""
        return ocr_text_is_usable(
            doc.flow_text,
            min_chars=self._ocr_min_chars,
            min_printable_ratio=self._ocr_min_printable_ratio,
            mean_confidence=doc.ocr_mean_confidence,
            min_confidence=self._ocr_min_confidence,
        )

    async def _recover_failed_pages(
        self,
        data: bytes,
        ocr_doc: ParsedDocument,
        *,
        page_count: int,
    ) -> ParsedDocument:
        """Replace only the pages OCR missed or garbled with Vision output.

        Sending the whole document to Vision because one page timed out used to
        re-bill every page to the model (observed ~15 s/page). The OCR text for the
        good pages is kept verbatim; only ``bad`` page numbers are rasterized.
        """
        page_vision = self._page_vision()
        if page_vision is None:
            return ocr_doc
        by_number = {page.number: page.text for page in ocr_doc.pages}
        bad = tuple(
            number
            for number in range(1, page_count + 1)
            if not ocr_text_is_usable(
                by_number.get(number, ""),
                min_chars=self._ocr_min_chars,
                min_printable_ratio=self._ocr_min_printable_ratio,
            )
        )
        if not bad:
            return ocr_doc
        try:
            recovered = await page_vision.parse_pages(data, page_numbers=bad)
        except DocumentParseError:
            logger.warning(
                "pdf page vision fallback failed; keeping OCR pages",
                pages=len(bad),
            )
            return ocr_doc
        recovered_text = {page.number: page.text for page in recovered.pages if page.text.strip()}
        if not recovered_text:
            return ocr_doc
        merged = dict(by_number)
        merged.update(recovered_text)
        pages = tuple(ParsedPage(number=number, text=merged[number]) for number in sorted(merged))
        logger.info(
            "pdf OCR pages escalated to vision individually",
            failed_pages=len(bad),
            recovered_pages=len(recovered_text),
        )
        return ocr_doc.model_copy(
            update={
                "pages": pages,
                "truncated": ocr_doc.truncated or recovered.truncated,
                "extraction_source": "vision",
                # The mean is document-wide; pages with low confidence were replaced,
                # so keeping the old value would fail a page that Vision just fixed.
                "ocr_mean_confidence": None,
            }
        )

    def _page_vision(self) -> _PageVision | None:
        """The Vision parser's page-level entry point, when this build has one."""
        if self._pdf_vision is None or not hasattr(self._pdf_vision, "parse_pages"):
            return None
        return cast("_PageVision", self._pdf_vision)


__all__ = ["RoutedDocumentParser"]
