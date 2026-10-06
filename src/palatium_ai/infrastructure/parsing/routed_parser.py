# src/palatium_ai/infrastructure/parsing/routed_parser.py

"""MIME + text-layer routing wrapper around leaf parsers (domain parse_routing)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

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
from palatium_ai.domain.ports.document_parser import DocumentParseError, ParsedDocument

if TYPE_CHECKING:
    from palatium_ai.domain.ports.document_parser import DocumentParserPort

logger = structlog.get_logger(__name__)


class _PdfFigureEnricher(Protocol):
    """Optional VLM figure pass for text-layer PDFs (G14)."""

    async def enrich_figures(self, data: bytes, base: ParsedDocument) -> ParsedDocument: ...


class RoutedDocumentParser:
    """Apply ``choose_parse_strategy`` after PDF text-layer extract; images stay leaf."""

    def __init__(
        self,
        *,
        inner: DocumentParserPort,
        model_supports_vision: bool,
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
        return await self._progressive_pdf_scan(data, mime_type=mime_type, filename=filename)

    async def _progressive_pdf_scan(
        self,
        data: bytes,
        *,
        mime_type: str,
        filename: str,
    ) -> ParsedDocument:
        """Tesseract OCR first; escalate to Vision on failure / low quality (2026)."""
        ocr_doc: ParsedDocument | None = None
        if self._pdf_ocr is not None:
            try:
                ocr_doc = await self._pdf_ocr.parse(data, mime_type=mime_type, filename=filename)
                if ocr_text_is_usable(
                    ocr_doc.flow_text,
                    min_chars=self._ocr_min_chars,
                    min_printable_ratio=self._ocr_min_printable_ratio,
                    mean_confidence=ocr_doc.ocr_mean_confidence,
                    min_confidence=self._ocr_min_confidence,
                ):
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


__all__ = ["RoutedDocumentParser"]
