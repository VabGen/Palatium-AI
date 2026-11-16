# tests/unit/test_routed_pdf_parser.py

"""RoutedDocumentParser: PDF text-layer probe then OCR fallback."""

from __future__ import annotations

import asyncio

import pytest

from palatium_ai.domain.ports.document_parser import DocumentParseError, ParsedDocument, ParsedPage
from palatium_ai.infrastructure.parsing.routed_parser import RoutedDocumentParser

pytestmark = pytest.mark.asyncio

_PARSE_TIMEOUT_SECONDS = 30.0


class _Leaf:
    def __init__(self, doc: ParsedDocument) -> None:
        self._doc = doc
        self.calls = 0

    def supports(self, mime_type: str) -> bool:
        return mime_type in {"application/pdf", "text/plain"}

    async def parse(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
        _ = data, mime_type, filename
        self.calls += 1
        return self._doc


class _PdfOcr:
    def __init__(self) -> None:
        self.calls = 0

    def supports(self, mime_type: str) -> bool:
        return mime_type == "application/pdf"

    async def parse(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
        _ = data, mime_type, filename
        self.calls += 1
        return ParsedDocument(
            pages=(ParsedPage(number=1, text="ocr page"),),
            extraction_source="ocr",
        )


class _PdfVision:
    def __init__(self) -> None:
        self.calls = 0

    def supports(self, mime_type: str) -> bool:
        return mime_type == "application/pdf"

    async def parse(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
        _ = data, mime_type, filename
        self.calls += 1
        return ParsedDocument(
            pages=(ParsedPage(number=1, text="vision page"),),
            extraction_source="vision",
        )


class _PageVision(_PdfVision):
    """Vision backend with the per-page entry point used by the OCR fallback."""

    def __init__(self) -> None:
        super().__init__()
        self.page_calls: list[tuple[int, ...]] = []

    async def parse_pages(
        self,
        data: bytes,
        *,
        page_numbers: tuple[int, ...],
    ) -> ParsedDocument:
        _ = data
        self.page_calls.append(page_numbers)
        return ParsedDocument(
            pages=tuple(ParsedPage(number=number, text=f"vision recovered page {number} text") for number in page_numbers),
            extraction_source="vision",
        )


async def test_routed_keeps_rich_pdf_text_layer() -> None:
    leaf = _Leaf(
        ParsedDocument(
            pages=(ParsedPage(number=1, text="x" * 500),),
            extraction_source="text_layer",
        )
    )
    ocr = _PdfOcr()
    routed = RoutedDocumentParser(
        inner=leaf,
        model_supports_vision=True,
        parse_timeout_seconds=_PARSE_TIMEOUT_SECONDS,
        pdf_ocr=ocr,
    )
    parsed = await routed.parse(b"%PDF", mime_type="application/pdf", filename="a.pdf")
    assert parsed.extraction_source == "text_layer"
    assert ocr.calls == 0


async def test_routed_calls_pdf_ocr_when_layer_sparse() -> None:
    leaf = _Leaf(
        ParsedDocument(
            pages=(ParsedPage(number=1, text=".."),),
            extraction_source="text_layer",
        )
    )
    ocr = _PdfOcr()
    routed = RoutedDocumentParser(
        inner=leaf,
        model_supports_vision=True,
        parse_timeout_seconds=_PARSE_TIMEOUT_SECONDS,
        pdf_ocr=ocr,
    )
    parsed = await routed.parse(b"%PDF", mime_type="application/pdf", filename="a.pdf")
    assert parsed.extraction_source == "ocr"
    assert ocr.calls == 1


async def test_routed_escalates_to_vision_when_ocr_quality_low() -> None:
    leaf = _Leaf(
        ParsedDocument(
            pages=(ParsedPage(number=1, text=""),),
            extraction_source="text_layer",
        )
    )

    class _WeakOcr(_PdfOcr):
        async def parse(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
            self.calls += 1
            _ = data, mime_type, filename
            return ParsedDocument(
                pages=(ParsedPage(number=1, text="@@"),),
                extraction_source="ocr",
            )

    ocr = _WeakOcr()
    vision = _PdfVision()
    routed = RoutedDocumentParser(
        inner=leaf,
        model_supports_vision=True,
        parse_timeout_seconds=_PARSE_TIMEOUT_SECONDS,
        pdf_ocr=ocr,
        pdf_vision=vision,
    )
    parsed = await routed.parse(b"%PDF", mime_type="application/pdf", filename="a.pdf")
    assert parsed.extraction_source == "vision"
    assert ocr.calls == 1
    assert vision.calls == 1


async def test_routed_escalates_only_failed_pages_to_vision() -> None:
    """A timed-out page must not re-bill the pages OCR already read (055)."""
    leaf = _Leaf(
        ParsedDocument(
            pages=(
                ParsedPage(number=1, text=""),
                ParsedPage(number=2, text=""),
            ),
            extraction_source="text_layer",
        )
    )

    class _PartialOcr(_PdfOcr):
        async def parse(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
            self.calls += 1
            _ = data, mime_type, filename
            return ParsedDocument(
                pages=(
                    ParsedPage(number=1, text=""),
                    ParsedPage(number=2, text="tesseract recovered page two text"),
                ),
                extraction_source="ocr",
            )

    ocr = _PartialOcr()
    vision = _PageVision()
    routed = RoutedDocumentParser(
        inner=leaf,
        model_supports_vision=True,
        parse_timeout_seconds=_PARSE_TIMEOUT_SECONDS,
        pdf_ocr=ocr,
        pdf_vision=vision,
    )

    parsed = await routed.parse(b"%PDF", mime_type="application/pdf", filename="a.pdf")

    assert vision.page_calls == [(1,)]
    assert vision.calls == 0
    assert parsed.extraction_source == "vision"
    assert parsed.pages[0].text == "vision recovered page 1 text"
    assert parsed.pages[1].text == "tesseract recovered page two text"


async def test_routed_skips_vision_when_every_ocr_page_is_usable() -> None:
    """No failed page → no per-page Vision calls at all."""
    leaf = _Leaf(
        ParsedDocument(
            pages=(
                ParsedPage(number=1, text=""),
                ParsedPage(number=2, text=""),
            ),
            extraction_source="text_layer",
        )
    )

    class _GoodOcr(_PdfOcr):
        async def parse(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
            self.calls += 1
            _ = data, mime_type, filename
            return ParsedDocument(
                pages=(
                    ParsedPage(number=1, text="first page OCR text is usable here"),
                    ParsedPage(number=2, text="second page OCR text is usable here"),
                ),
                extraction_source="ocr",
            )

    vision = _PageVision()
    routed = RoutedDocumentParser(
        inner=leaf,
        model_supports_vision=True,
        parse_timeout_seconds=_PARSE_TIMEOUT_SECONDS,
        pdf_ocr=_GoodOcr(),
        pdf_vision=vision,
    )

    parsed = await routed.parse(b"%PDF", mime_type="application/pdf", filename="a.pdf")

    assert vision.page_calls == []
    assert vision.calls == 0
    assert parsed.extraction_source == "ocr"


async def test_routed_fails_closed_without_ocr_backend() -> None:
    leaf = _Leaf(
        ParsedDocument(
            pages=(ParsedPage(number=1, text=""),),
            extraction_source="text_layer",
        )
    )
    routed = RoutedDocumentParser(
        inner=leaf,
        model_supports_vision=False,
        parse_timeout_seconds=_PARSE_TIMEOUT_SECONDS,
        pdf_ocr=None,
    )
    with pytest.raises(DocumentParseError, match="no usable text layer"):
        await routed.parse(b"%PDF", mime_type="application/pdf", filename="a.pdf")


class _HangingLeaf:
    """Stands in for a parser stuck in an unbounded library call."""

    def __init__(self) -> None:
        self.calls = 0

    def supports(self, mime_type: str) -> bool:
        return mime_type == "application/pdf"

    async def parse(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
        _ = data, mime_type, filename
        self.calls += 1
        await asyncio.sleep(30)
        raise AssertionError("the budget must cancel this parse")


async def test_routed_parse_budget_fails_closed() -> None:
    """Regression: an unbounded parse used to hold ``POST /complete`` forever."""
    routed = RoutedDocumentParser(
        inner=_HangingLeaf(),
        model_supports_vision=False,
        parse_timeout_seconds=0.01,
    )
    with pytest.raises(DocumentParseError, match="time budget"):
        await routed.parse(b"%PDF", mime_type="application/pdf", filename="a.pdf")
