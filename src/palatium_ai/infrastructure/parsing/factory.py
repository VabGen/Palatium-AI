# src/palatium_ai/infrastructure/parsing/factory.py

"""DocumentParserPort factory.

Optional parsers are registered only when their library is importable, so a lean
install degrades to "this media type cannot be parsed yet" (an explicit,
fail-closed rejection at intake) instead of an ImportError deep inside a request.
"""

from __future__ import annotations

import importlib.util

from typing import TYPE_CHECKING

from palatium_ai.core.logging import logger
from palatium_ai.domain.ports.document_parser import DocumentParserPort
from palatium_ai.infrastructure.parsing.document_parser import (
    CompositeDocumentParser,
    DocxParser,
    HtmlParser,
    PdfParser,
    PlainTextParser,
    PptxParser,
    XlsxParser,
)
from palatium_ai.infrastructure.parsing.image_ocr import GatewayImageOcrParser
from palatium_ai.infrastructure.parsing.pdf_ocr import TesseractPdfOcrParser
from palatium_ai.infrastructure.parsing.pdf_vision import GatewayPdfVisionParser
from palatium_ai.infrastructure.parsing.routed_parser import RoutedDocumentParser
from palatium_ai.infrastructure.parsing.tesseract_ocr import FallbackImageOcrParser, TesseractImageOcrParser

if TYPE_CHECKING:
    from palatium_ai.core.config.attachments import AttachmentConfig
    from palatium_ai.core.config.settings import Settings

_TEXT_MEDIA_TYPES = ("text/plain", "text/markdown", "text/csv")

# MIME -> importable module name of the extra that provides the matching parser.
# This is the *module* name, not the distribution name: ``importlib.util.find_spec``
# resolves modules, and ``python-docx`` installs ``docx`` (a distribution name
# with a dash is not importable, so the probe would always miss).
_OPTIONAL_PARSERS: tuple[tuple[str, str], ...] = (
    ("application/pdf", "pypdf"),
    ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "openpyxl"),
    ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "lxml"),
    ("text/html", "lxml"),
)


def _module_available(module_name: str) -> bool:
    """Whether a distribution is importable, without importing it."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def build_document_parser(settings: Settings) -> DocumentParserPort:
    """Build the composite parser with the limits from configuration."""
    config = settings.attachments
    parsers, rejected = _collect_leaf_parsers(config)

    image_parser, vision_available = _build_image_ocr_parser(settings, config)
    if image_parser is not None:
        parsers.append(image_parser)

    leaf = CompositeDocumentParser(parsers)
    pdf_ocr, pdf_vision = _build_pdf_backends(settings, config, model_supports_vision=vision_available)

    logger.info(
        "DocumentParserPort: local",
        parsers=len(parsers),
        rejected_media_types=rejected,
        pdf_ocr=pdf_ocr is not None,
        pdf_vision=pdf_vision is not None,
        vision=vision_available,
        image_ocr_backend=config.image_ocr_backend,
        tesseract_cmd=bool((config.tesseract_cmd or "").strip()),
    )
    return RoutedDocumentParser(
        inner=leaf,
        model_supports_vision=vision_available,
        pdf_ocr=pdf_ocr,
        pdf_vision=pdf_vision,
        figure_enricher=pdf_vision if config.pdf_figure_enrichment else None,
        min_avg_chars_per_page=config.pdf_min_avg_chars_per_page,
        ocr_min_chars=config.ocr_min_chars,
        ocr_min_printable_ratio=config.ocr_min_printable_ratio,
        ocr_min_confidence=config.ocr_min_confidence,
    )


def _collect_leaf_parsers(config: AttachmentConfig) -> tuple[list[DocumentParserPort], list[str]]:
    """Register text + optional Office/HTML parsers; skip missing extras fail-closed."""
    parsers: list[DocumentParserPort] = [
        PlainTextParser(media_types=_TEXT_MEDIA_TYPES, max_chars=config.max_parsed_chars),
    ]
    rejected: list[str] = []
    for mime_type, module_name in _OPTIONAL_PARSERS:
        if not _module_available(module_name):
            rejected.append(mime_type)
            logger.warning(
                "Attachment parser unavailable; media type will be rejected at intake",
                mime_type=mime_type,
                package=module_name,
            )
            continue
        parsers.append(_optional_parser(mime_type, config))
    return parsers, rejected


def _optional_parser(mime_type: str, config: AttachmentConfig) -> DocumentParserPort:
    """Instantiate the parser for one optional media type (already import-probed)."""
    if mime_type == "application/pdf":
        return PdfParser(max_chars=config.max_parsed_chars, max_pages=config.max_parsed_pages)
    if mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        return XlsxParser(max_chars=config.max_parsed_chars, max_pages=config.max_parsed_pages)
    if mime_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
        return PptxParser(max_chars=config.max_parsed_chars, max_pages=config.max_parsed_pages)
    if mime_type == "text/html":
        return HtmlParser(max_chars=config.max_parsed_chars)
    return DocxParser(max_chars=config.max_parsed_chars)


def _build_pdf_backends(
    settings: Settings,
    config: AttachmentConfig,
    *,
    model_supports_vision: bool,
) -> tuple[DocumentParserPort | None, GatewayPdfVisionParser | None]:
    """Optional PDF OCR / vision backends layered by RoutedDocumentParser."""
    pdf_ocr: DocumentParserPort | None = None
    pdf_vision: GatewayPdfVisionParser | None = None
    tesseract_cmd = (config.tesseract_cmd or "").strip() or None
    if _module_available("fitz") and _module_available("pytesseract"):
        pdf_ocr = TesseractPdfOcrParser(
            max_chars=config.max_parsed_chars,
            max_pages=min(config.max_parsed_pages, 10),
            tesseract_cmd=tesseract_cmd,
        )
    if model_supports_vision and _module_available("fitz"):
        model = (config.image_ocr_model or "").strip()
        gateway = getattr(getattr(settings, "llm", None), "gateway", None)
        if gateway is not None and model:
            pdf_vision = GatewayPdfVisionParser(
                config=gateway,
                model=model,
                max_chars=config.max_parsed_chars,
                max_pages=min(config.max_parsed_pages, config.pdf_vision_max_pages),
                max_bytes=config.image_ocr_max_bytes,
                timeout_seconds=config.image_ocr_timeout_seconds,
                figure_enrichment=config.pdf_figure_enrichment,
                max_figure_pages=config.pdf_figure_max_pages,
            )
    return pdf_ocr, pdf_vision


def _optional_tesseract_image(config: AttachmentConfig) -> DocumentParserPort | None:
    """Local Tesseract image OCR when pytesseract + Pillow are importable."""
    if not (_module_available("pytesseract") and _module_available("PIL")):
        return None
    tesseract_cmd = (config.tesseract_cmd or "").strip() or None
    return TesseractImageOcrParser(
        max_chars=config.max_parsed_chars,
        max_bytes=config.image_ocr_max_bytes,
        tesseract_cmd=tesseract_cmd,
    )


def _optional_vision_image(
    settings: Settings,
    config: AttachmentConfig,
) -> DocumentParserPort | None:
    """Gateway Vision image OCR when model alias + gateway config are present."""
    model = (config.image_ocr_model or "").strip()
    gateway = getattr(getattr(settings, "llm", None), "gateway", None)
    if gateway is None or not model:
        return None
    return GatewayImageOcrParser(
        config=gateway,
        model=model,
        max_chars=config.max_parsed_chars,
        max_bytes=config.image_ocr_max_bytes,
        timeout_seconds=config.image_ocr_timeout_seconds,
    )


def _wire_gateway_image_ocr(
    *,
    tesseract: DocumentParserPort | None,
    vision: DocumentParserPort | None,
    config: AttachmentConfig,
    model: str,
) -> tuple[DocumentParserPort | None, bool]:
    """Vision-primary chain for ``image_ocr_backend=gateway``."""
    if vision is None:
        logger.warning(
            "Image OCR gateway backend without a usable model/gateway; falling back to tesseract if present",
        )
        return tesseract, False
    logger.info("Image OCR parser wired", backend="gateway", model=model, primary="vision")
    if tesseract is None:
        return vision, True
    # Vision primary; Tesseract if Vision errors or text fails the quality gate.
    return (
        FallbackImageOcrParser(
            primary=vision,
            fallback=tesseract,
            min_chars=config.ocr_min_chars,
            min_printable_ratio=config.ocr_min_printable_ratio,
            min_confidence=config.ocr_min_confidence,
        ),
        True,
    )


def _wire_auto_image_ocr(
    *,
    tesseract: DocumentParserPort | None,
    vision: DocumentParserPort | None,
    config: AttachmentConfig,
    model: str,
) -> tuple[DocumentParserPort | None, bool]:
    """Tesseract-first progressive chain for ``image_ocr_backend=auto``."""
    if tesseract is not None and vision is not None:
        logger.info("Image OCR parser wired", backend="auto", model=model, primary="tesseract")
        return (
            FallbackImageOcrParser(
                primary=tesseract,
                fallback=vision,
                min_chars=config.ocr_min_chars,
                min_printable_ratio=config.ocr_min_printable_ratio,
                min_confidence=config.ocr_min_confidence,
            ),
            True,
        )
    if tesseract is not None:
        logger.info("Image OCR parser wired", backend="auto", primary="tesseract", vision=False)
        return tesseract, False
    if vision is not None:
        logger.info("Image OCR parser wired", backend="auto", primary="vision", tesseract=False)
        return vision, True
    logger.warning(
        "ATTACHMENTS_IMAGE_OCR_BACKEND=auto but neither Tesseract nor Vision is available; image/* refused",
    )
    return None, False


def _build_image_ocr_parser(
    settings: Settings,
    config: AttachmentConfig,
) -> tuple[DocumentParserPort | None, bool]:
    """Wire progressive image OCR (Tesseract → Vision) per ``image_ocr_backend``.

    Returns ``(parser, vision_available)``. When no parser is registered the
    composite does not ``supports()`` any ``image/*`` type, so capability-gated
    intake refuses images immediately (055).
    """
    if config.image_ocr_backend == "disabled":
        return None, False

    tesseract = _optional_tesseract_image(config)
    vision = _optional_vision_image(settings, config)
    model = (config.image_ocr_model or "").strip()
    backend = config.image_ocr_backend

    if backend == "tesseract":
        if tesseract is None:
            logger.warning("ATTACHMENTS_IMAGE_OCR_BACKEND=tesseract but pytesseract/Pillow missing")
        return tesseract, False
    if backend == "gateway":
        return _wire_gateway_image_ocr(tesseract=tesseract, vision=vision, config=config, model=model)
    return _wire_auto_image_ocr(tesseract=tesseract, vision=vision, config=config, model=model)
