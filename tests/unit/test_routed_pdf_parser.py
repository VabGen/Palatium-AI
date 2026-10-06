# tests/unit/test_routed_pdf_parser.py

"""RoutedDocumentParser: PDF text-layer probe then OCR fallback."""

from __future__ import annotations

import pytest

from palatium_ai.domain.ports.document_parser import DocumentParseError, ParsedDocument, ParsedPage
from palatium_ai.infrastructure.parsing.routed_parser import RoutedDocumentParser

pytestmark = pytest.mark.asyncio


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


async def test_routed_keeps_rich_pdf_text_layer() -> None:
    leaf = _Leaf(
        ParsedDocument(
            pages=(ParsedPage(number=1, text="x" * 500),),
            extraction_source="text_layer",
        )
    )
    ocr = _PdfOcr()
    routed = RoutedDocumentParser(inner=leaf, model_supports_vision=True, pdf_ocr=ocr)
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
    routed = RoutedDocumentParser(inner=leaf, model_supports_vision=True, pdf_ocr=ocr)
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
        pdf_ocr=ocr,
        pdf_vision=vision,
    )
    parsed = await routed.parse(b"%PDF", mime_type="application/pdf", filename="a.pdf")
    assert parsed.extraction_source == "vision"
    assert ocr.calls == 1
    assert vision.calls == 1


async def test_routed_fails_closed_without_ocr_backend() -> None:
    leaf = _Leaf(
        ParsedDocument(
            pages=(ParsedPage(number=1, text=""),),
            extraction_source="text_layer",
        )
    )
    routed = RoutedDocumentParser(inner=leaf, model_supports_vision=False, pdf_ocr=None)
    with pytest.raises(DocumentParseError, match="no usable text layer"):
        await routed.parse(b"%PDF", mime_type="application/pdf", filename="a.pdf")
