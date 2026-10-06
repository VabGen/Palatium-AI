# src/palatium_ai/domain/attachments/parse_routing.py

"""Deterministic parse-strategy selection for attachments (055, 070).

Strategy is chosen from MIME + extracted text-layer sufficiency — never from an
LLM classifier and never from file byte size alone (scanned 100 KiB still needs
OCR; a large PDF with a text layer does not).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: Empirically empty/near-empty PDF text layers fall below this average.
DEFAULT_MIN_AVG_CHARS_PER_PAGE = 200

#: Progressive OCR: escalate to vision when local OCR yields fewer chars than this.
DEFAULT_OCR_MIN_CHARS = 12

#: Progressive OCR: escalate when printable (letters/digits/space) ratio is below this.
DEFAULT_OCR_MIN_PRINTABLE_RATIO = 0.55

#: Progressive OCR: escalate when Tesseract mean word confidence is below this (0–100).
#: Handwritten Cyrillic often yields Latin gibberish that still passes printable-ratio.
DEFAULT_OCR_MIN_CONFIDENCE = 55.0

#: Soft paste→attach threshold mirrored by the web client (``AUTO_ATTACH_CHARS``).
AUTO_ATTACH_CHARS = 10_000

#: Hard intent ``text`` cap (``ClassifyIntentRequest`` / web ``INTENT_TEXT_LIMIT``).
INTENT_TEXT_LIMIT = 32_000

ParseStrategy = Literal["text_layer", "vision", "ocr", "refuse"]
TextFromChatRoute = Literal["text_only", "attach_text", "refuse_too_large"]
ExtractionSource = Literal["text_layer", "vision", "ocr", "none"]


class ParseRouteDecision(BaseModel):
    """Outcome of ``choose_parse_strategy`` — pure, unit-testable."""

    model_config = {"frozen": True}

    strategy: ParseStrategy
    reason: str = Field(min_length=1, max_length=128)


class TextFromChatDecision(BaseModel):
    """Outcome of ``route_text_from_chat`` for composer paste/typing length."""

    model_config = {"frozen": True}

    route: TextFromChatRoute
    reason: str = Field(min_length=1, max_length=128)


def text_layer_is_sufficient(
    *,
    total_chars: int,
    page_count: int,
    min_avg_chars_per_page: int = DEFAULT_MIN_AVG_CHARS_PER_PAGE,
) -> bool:
    """Whether extracted PDF/page text is dense enough to skip OCR."""
    if page_count <= 0 or total_chars <= 0:
        return False
    return (total_chars / page_count) >= min_avg_chars_per_page


def ocr_text_is_usable(
    text: str,
    *,
    min_chars: int = DEFAULT_OCR_MIN_CHARS,
    min_printable_ratio: float = DEFAULT_OCR_MIN_PRINTABLE_RATIO,
    mean_confidence: float | None = None,
    min_confidence: float = DEFAULT_OCR_MIN_CONFIDENCE,
) -> bool:
    """Whether local OCR output is good enough to skip a Vision escalate (2026 progressive).

    Empty / near-empty / high-garbage strings fail closed toward the VLM fallback.
    When Tesseract reports ``mean_confidence``, low scores also escalate — printable
    Latin gibberish from Cyrillic handwriting otherwise falsely passes the ratio gate.
    Vision paths leave ``mean_confidence=None`` (text-only checks).
    """
    stripped = text.strip()
    if len(stripped) < min_chars:
        return False
    if mean_confidence is not None and mean_confidence < min_confidence:
        return False
    if min_printable_ratio <= 0.0:
        return True
    printable = sum(1 for ch in stripped if ch.isalnum() or ch.isspace() or ch in ".,;:!?%-/()[]\"'")
    return (printable / len(stripped)) >= min_printable_ratio


def choose_parse_strategy(
    *,
    mime_type: str,
    model_supports_vision: bool,
    text_layer_chars: int | None = None,
    page_count: int | None = None,
    min_avg_chars_per_page: int = DEFAULT_MIN_AVG_CHARS_PER_PAGE,
) -> ParseRouteDecision:
    """Select extraction strategy from MIME (+ optional PDF text-layer probe)."""
    normalized = mime_type.strip().lower()
    _ = model_supports_vision  # retained for callers; escalate is progressive in the router

    if normalized.startswith("image/"):
        # Cheap local OCR first; Vision is the escalate path in FallbackImageOcrParser.
        return ParseRouteDecision(strategy="ocr", reason="image_ocr_primary")

    if normalized == "application/pdf":
        if text_layer_chars is None or page_count is None:
            return ParseRouteDecision(strategy="text_layer", reason="pdf_probe_pending")
        if text_layer_is_sufficient(
            total_chars=text_layer_chars,
            page_count=page_count,
            min_avg_chars_per_page=min_avg_chars_per_page,
        ):
            return ParseRouteDecision(strategy="text_layer", reason="pdf_text_layer_ok")
        # Progressive: Tesseract OCR first, Vision escalate in RoutedDocumentParser.
        return ParseRouteDecision(strategy="ocr", reason="pdf_scan_ocr_first")

    if normalized in {
        "text/plain",
        "text/markdown",
        "text/csv",
        "text/html",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }:
        return ParseRouteDecision(strategy="text_layer", reason="structured_text")

    return ParseRouteDecision(strategy="refuse", reason="unsupported_mime")


def route_text_from_chat(
    text: str,
    *,
    auto_attach_chars: int = AUTO_ATTACH_CHARS,
    intent_text_limit: int = INTENT_TEXT_LIMIT,
    max_attachment_bytes: int,
) -> TextFromChatDecision:
    """Route composer text by length; byte cap refuses oversized paste-as-file."""
    n = len(text)
    if n == 0:
        return TextFromChatDecision(route="text_only", reason="empty")
    utf8_bytes = len(text.encode("utf-8"))
    if utf8_bytes > max_attachment_bytes:
        return TextFromChatDecision(route="refuse_too_large", reason="over_attachment_bytes")
    if n <= auto_attach_chars:
        return TextFromChatDecision(route="text_only", reason="under_auto_attach")
    if n <= intent_text_limit:
        # Still legal as intent text; paste UX converts, typing may stay.
        return TextFromChatDecision(route="attach_text", reason="paste_prefer_attach")
    return TextFromChatDecision(route="attach_text", reason="over_intent_must_attach")


__all__ = [
    "AUTO_ATTACH_CHARS",
    "DEFAULT_MIN_AVG_CHARS_PER_PAGE",
    "DEFAULT_OCR_MIN_CHARS",
    "DEFAULT_OCR_MIN_CONFIDENCE",
    "DEFAULT_OCR_MIN_PRINTABLE_RATIO",
    "INTENT_TEXT_LIMIT",
    "ExtractionSource",
    "ParseRouteDecision",
    "ParseStrategy",
    "TextFromChatDecision",
    "TextFromChatRoute",
    "choose_parse_strategy",
    "ocr_text_is_usable",
    "route_text_from_chat",
    "text_layer_is_sufficient",
]
