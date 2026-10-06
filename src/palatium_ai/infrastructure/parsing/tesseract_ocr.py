# src/palatium_ai/infrastructure/parsing/tesseract_ocr.py

"""Local Tesseract OCR + progressive escalate to Vision (2026 best practice)."""

from __future__ import annotations

import asyncio

from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog

from palatium_ai.domain.attachments.parse_routing import (
    DEFAULT_OCR_MIN_CHARS,
    DEFAULT_OCR_MIN_CONFIDENCE,
    DEFAULT_OCR_MIN_PRINTABLE_RATIO,
    ocr_text_is_usable,
)
from palatium_ai.domain.ports.document_parser import (
    DocumentParseError,
    DocumentParserPort,
    ParsedDocument,
    ParsedPage,
)
from palatium_ai.infrastructure.parsing.image_decode_guard import assert_image_decode_within_budget
from palatium_ai.infrastructure.parsing.image_ocr import IMAGE_MEDIA_TYPES

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = structlog.get_logger(__name__)


class TesseractImageOcrParser:
    """Transcribe ``image/*`` with a local Tesseract binary when installed."""

    def __init__(
        self,
        *,
        max_chars: int,
        max_bytes: int,
        media_types: Iterable[str] | None = None,
        lang: str = "eng+rus",
        tesseract_cmd: str | None = None,
    ) -> None:
        self._max_chars = max_chars
        self._max_bytes = max_bytes
        self._media_types = frozenset(media_types) if media_types is not None else frozenset(IMAGE_MEDIA_TYPES)
        self._lang = lang
        self._tesseract_cmd = (tesseract_cmd or "").strip() or None

    def supports(self, mime_type: str) -> bool:
        """Whether this adapter handles the media type."""
        return mime_type in self._media_types

    async def parse(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
        """Run Tesseract off the event loop; missing extras → typed parse error."""
        _ = filename
        if len(data) > self._max_bytes:
            msg = f"image is {len(data)} bytes, over the {self._max_bytes} byte OCR payload cap"
            raise DocumentParseError(msg)
        assert_image_decode_within_budget(data)
        text, mean_confidence = await asyncio.to_thread(self._transcribe_sync, data, mime_type)
        truncated = len(text) > self._max_chars
        body = text if not truncated else _truncate_at_word(text, self._max_chars)
        return ParsedDocument(
            pages=(ParsedPage(number=1, text=body),),
            truncated=truncated,
            extraction_source="ocr",
            ocr_mean_confidence=mean_confidence,
        )

    def _transcribe_sync(self, data: bytes, mime_type: str) -> tuple[str, float | None]:
        try:
            import pytesseract

            from PIL import Image
        except ImportError as exc:
            msg = "tesseract OCR extras missing; install Pillow and pytesseract"
            raise DocumentParseError(msg) from exc

        if self._tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self._tesseract_cmd

        try:
            from io import BytesIO

            image = Image.open(BytesIO(data))
            # Explicit load so a truncated payload fails here, not inside tesseract.
            image.load()
            payload = pytesseract.image_to_data(image, lang=self._lang, output_type=pytesseract.Output.DICT)
        except DocumentParseError:
            raise
        except Exception as exc:
            logger.warning(
                "tesseract OCR failed",
                error_type=type(exc).__name__,
                media_type=mime_type,
            )
            msg = "tesseract OCR failed"
            raise DocumentParseError(msg) from exc
        return _words_and_mean_confidence(payload)


def _words_and_mean_confidence(payload: dict[str, list[object]]) -> tuple[str, float | None]:
    """Join Tesseract words and average confidences (skip ``conf < 0`` non-words)."""
    texts = payload.get("text") or []
    confs = payload.get("conf") or []
    words: list[str] = []
    scores: list[float] = []
    for raw_text, raw_conf in zip(texts, confs, strict=False):
        word = str(raw_text).strip()
        if not word:
            continue
        if not isinstance(raw_conf, (int, float, str)):
            continue
        try:
            conf = float(raw_conf)
        except ValueError:
            continue
        if conf < 0.0:
            continue
        words.append(word)
        scores.append(conf)
    if not words:
        return "", None
    mean = sum(scores) / len(scores)
    return " ".join(words), round(mean, 2)


class FallbackImageOcrParser:
    """Progressive chain: primary (cheap OCR) → quality gate → fallback (Vision).

    Primary failure or unusable text escalates to Vision. Returning an unusable
    primary after Vision also fails is forbidden: that admitted empty/garbage
    images and made the chat invent "images cannot be read" (020, 055).
    """

    def __init__(
        self,
        *,
        primary: DocumentParserPort,
        fallback: DocumentParserPort,
        text_is_usable: Callable[[ParsedDocument], bool] | None = None,
        min_chars: int = DEFAULT_OCR_MIN_CHARS,
        min_printable_ratio: float = DEFAULT_OCR_MIN_PRINTABLE_RATIO,
        min_confidence: float = DEFAULT_OCR_MIN_CONFIDENCE,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._min_chars = min_chars
        self._min_printable_ratio = min_printable_ratio
        self._min_confidence = min_confidence
        self._text_is_usable = text_is_usable or self._default_usable

    def _default_usable(self, doc: ParsedDocument) -> bool:
        return ocr_text_is_usable(
            doc.flow_text,
            min_chars=self._min_chars,
            min_printable_ratio=self._min_printable_ratio,
            mean_confidence=doc.ocr_mean_confidence,
            min_confidence=self._min_confidence,
        )

    def supports(self, mime_type: str) -> bool:
        """True when either backend claims the MIME."""
        return self._primary.supports(mime_type) or self._fallback.supports(mime_type)

    async def parse(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
        """Try primary OCR; escalate to Vision on error or low-quality text."""
        primary_doc: ParsedDocument | None = None
        if self._primary.supports(mime_type):
            try:
                primary_doc = await self._primary.parse(data, mime_type=mime_type, filename=filename)
                if self._text_is_usable(primary_doc):
                    return primary_doc
                logger.info(
                    "primary OCR quality insufficient; escalating to vision fallback",
                    chars=len(primary_doc.flow_text.strip()),
                    mean_confidence=primary_doc.ocr_mean_confidence,
                )
            except DocumentParseError as primary_exc:
                logger.warning(
                    "primary OCR failed; escalating to vision fallback",
                    error_type=type(primary_exc).__name__,
                )

        if not self._fallback.supports(mime_type):
            if primary_doc is not None and self._text_is_usable(primary_doc):
                return primary_doc
            msg = "image OCR unavailable after primary failure"
            raise DocumentParseError(msg)

        try:
            fallback_doc = await self._fallback.parse(data, mime_type=mime_type, filename=filename)
        except DocumentParseError:
            if primary_doc is not None and self._text_is_usable(primary_doc):
                return primary_doc
            raise

        if self._text_is_usable(fallback_doc):
            return fallback_doc
        if primary_doc is not None and self._text_is_usable(primary_doc):
            return primary_doc
        msg = "image OCR produced no usable text after progressive chain"
        raise DocumentParseError(msg)


def _truncate_at_word(text: str, max_chars: int) -> str:
    """Prefer a whitespace cut so OCR caps do not end mid-token."""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    piece = text[:max_chars]
    space = piece.rfind(" ")
    if space > max_chars // 2:
        return piece[:space].rstrip()
    return piece.rstrip()


__all__ = ["FallbackImageOcrParser", "TesseractImageOcrParser"]
