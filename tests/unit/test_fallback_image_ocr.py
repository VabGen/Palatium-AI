# tests/unit/test_fallback_image_ocr.py

"""Progressive OCR: Tesseract (primary) → Vision (fallback) + quality gate."""

from __future__ import annotations

import pytest

from palatium_ai.domain.ports.document_parser import DocumentParseError, ParsedDocument, ParsedPage
from palatium_ai.infrastructure.parsing.tesseract_ocr import FallbackImageOcrParser

pytestmark = pytest.mark.asyncio


class _StubParser:
    def __init__(self, *, supports: bool, result: ParsedDocument | None = None, error: str | None = None) -> None:
        self._supports = supports
        self._result = result
        self._error = error
        self.calls = 0

    def supports(self, mime_type: str) -> bool:
        _ = mime_type
        return self._supports

    async def parse(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
        _ = data, mime_type, filename
        self.calls += 1
        if self._error is not None:
            raise DocumentParseError(self._error)
        assert self._result is not None
        return self._result


async def test_fallback_keeps_usable_primary_ocr() -> None:
    ok = ParsedDocument(
        pages=(ParsedPage(number=1, text="printed invoice total 1200"),),
        extraction_source="ocr",
    )
    primary = _StubParser(supports=True, result=ok)
    fallback = _StubParser(
        supports=True,
        result=ParsedDocument(pages=(ParsedPage(number=1, text="from vision"),), extraction_source="vision"),
    )
    parser = FallbackImageOcrParser(primary=primary, fallback=fallback)
    parsed = await parser.parse(b"img", mime_type="image/png", filename="a.png")
    assert parsed.pages[0].text.startswith("printed invoice")
    assert primary.calls == 1
    assert fallback.calls == 0


async def test_fallback_escalates_when_primary_fails() -> None:
    primary = _StubParser(supports=True, error="tesseract down")
    fallback = _StubParser(
        supports=True,
        result=ParsedDocument(pages=(ParsedPage(number=1, text="from vision model OCR"),), extraction_source="vision"),
    )
    parser = FallbackImageOcrParser(primary=primary, fallback=fallback)
    parsed = await parser.parse(b"img", mime_type="image/png", filename="a.png")
    assert parsed.pages[0].text == "from vision model OCR"
    assert parsed.extraction_source == "vision"
    assert primary.calls == 1
    assert fallback.calls == 1


async def test_fallback_escalates_on_low_tesseract_confidence() -> None:
    """Handwriting Cyrillic → Latin gibberish is printable; confidence must escalate."""
    primary = _StubParser(
        supports=True,
        result=ParsedDocument(
            pages=(ParsedPage(number=1, text="Lede ve ne Cale RTE SOLD ge SOON"),),
            extraction_source="ocr",
            ocr_mean_confidence=31.0,
        ),
    )
    fallback = _StubParser(
        supports=True,
        result=ParsedDocument(
            pages=(ParsedPage(number=1, text="Цена на Иван-чай выросла"),),
            extraction_source="vision",
        ),
    )
    parser = FallbackImageOcrParser(primary=primary, fallback=fallback)
    parsed = await parser.parse(b"img", mime_type="image/webp", filename="ht.webp")
    assert parsed.extraction_source == "vision"
    assert "Иван-чай" in parsed.pages[0].text
    assert fallback.calls == 1


async def test_fallback_keeps_high_confidence_primary() -> None:
    ok = ParsedDocument(
        pages=(ParsedPage(number=1, text="printed invoice total 1200"),),
        extraction_source="ocr",
        ocr_mean_confidence=88.0,
    )
    primary = _StubParser(supports=True, result=ok)
    fallback = _StubParser(
        supports=True,
        result=ParsedDocument(pages=(ParsedPage(number=1, text="from vision"),), extraction_source="vision"),
    )
    parser = FallbackImageOcrParser(primary=primary, fallback=fallback)
    parsed = await parser.parse(b"img", mime_type="image/png", filename="a.png")
    assert parsed.pages[0].text.startswith("printed invoice")
    assert fallback.calls == 0


async def test_fallback_fails_closed_when_vision_returns_unusable() -> None:
    """Empty Vision success must not admit the attachment (chat invented 'can't read webp')."""
    primary = _StubParser(
        supports=True,
        result=ParsedDocument(pages=(ParsedPage(number=1, text="ab"),), extraction_source="ocr"),
    )
    fallback = _StubParser(
        supports=True,
        result=ParsedDocument(pages=(ParsedPage(number=1, text=""),), extraction_source="vision"),
    )
    parser = FallbackImageOcrParser(primary=primary, fallback=fallback)
    with pytest.raises(DocumentParseError, match="no usable text"):
        await parser.parse(b"img", mime_type="image/webp", filename="a.webp")


async def test_fallback_fails_closed_when_vision_errors_and_primary_unusable() -> None:
    weak = ParsedDocument(pages=(ParsedPage(number=1, text="ab"),), extraction_source="ocr")
    primary = _StubParser(supports=True, result=weak)
    fallback = _StubParser(supports=True, error="vision down")
    parser = FallbackImageOcrParser(primary=primary, fallback=fallback)
    with pytest.raises(DocumentParseError, match="vision"):
        await parser.parse(b"img", mime_type="image/png", filename="a.png")


async def test_fallback_fails_closed_when_both_fail() -> None:
    primary = _StubParser(supports=True, error="tesseract down")
    fallback = _StubParser(supports=True, error="vision down")
    parser = FallbackImageOcrParser(primary=primary, fallback=fallback)
    with pytest.raises(DocumentParseError, match="vision"):
        await parser.parse(b"img", mime_type="image/png", filename="a.png")
