"""OCR guardrails: unbounded Tesseract is the "infinite spinner" root cause (080).

Regression: ``pytesseract`` was called without ``timeout``, so a pathological page
kept the child process (and the synchronous ``POST /complete`` behind it) alive
forever. These tests pin the three defences: per-call hard kill, per-document
budget, and one OCR slot per process.
"""

from __future__ import annotations

import asyncio
import sys
import time

from types import SimpleNamespace
from typing import Any

import pytest

from palatium_ai.domain.ports.document_parser import DocumentParseError
from palatium_ai.infrastructure.parsing import (
    pdf_ocr as pdf_ocr_module,
    tesseract_ocr as image_ocr_module,
)
from palatium_ai.infrastructure.parsing.pdf_ocr import TesseractPdfOcrParser
from palatium_ai.infrastructure.parsing.tesseract_ocr import TesseractImageOcrParser

pytestmark = pytest.mark.asyncio

_TIMEOUT_SECONDS = 90.0
_BUDGET_SECONDS = 300.0


def _fake_fitz(page_count: int) -> SimpleNamespace:
    """Minimal PyMuPDF surface used by the adapter (rasterize + close)."""
    page = SimpleNamespace(
        get_pixmap=lambda **_: SimpleNamespace(width=1, height=1, samples=b"\x00\x00\x00"),
    )
    doc = SimpleNamespace(
        page_count=page_count,
        load_page=lambda _index: page,
        close=lambda: None,
    )
    return SimpleNamespace(
        Matrix=lambda *_args: object(),
        open=lambda **_: doc,
    )


def _install_pdf_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    image_to_string: Any,
) -> None:
    fake_pytesseract = SimpleNamespace(
        pytesseract=SimpleNamespace(tesseract_cmd=""),
        image_to_string=image_to_string,
    )
    fake_pil = SimpleNamespace(Image=SimpleNamespace(frombytes=lambda *_: object()))
    monkeypatch.setitem(sys.modules, "fitz", _fake_fitz(page_count=2))
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)


def _pdf_parser(*, budget_seconds: float = _BUDGET_SECONDS) -> TesseractPdfOcrParser:
    return TesseractPdfOcrParser(
        max_chars=10_000,
        max_pages=10,
        timeout_seconds=_TIMEOUT_SECONDS,
        budget_seconds=budget_seconds,
        limiter=asyncio.Semaphore(1),
        tesseract_cmd=None,
    )


async def test_pdf_ocr_passes_timeout_and_refuses_on_hang(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def _hang(*_args: object, **kwargs: Any) -> str:
        calls.append(kwargs)
        raise RuntimeError("Tesseract process timeout")

    _install_pdf_modules(monkeypatch, image_to_string=_hang)

    with pytest.raises(DocumentParseError, match="no text"):
        await _pdf_parser().parse(b"%PDF", mime_type="application/pdf", filename="scan.pdf")

    # The child is killed by pytesseract only because the timeout is passed through,
    # and a hung page stops the document instead of burning the same budget again.
    assert calls == [{"lang": "eng+rus", "timeout": _TIMEOUT_SECONDS}]


async def test_pdf_ocr_stops_when_document_budget_is_spent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def _page(*_args: object, **_kwargs: Any) -> str:
        calls.append(1)
        return "page text"

    _install_pdf_modules(monkeypatch, image_to_string=_page)
    clock = iter([0.0, 1.0, 10_000.0])
    monkeypatch.setattr(pdf_ocr_module.time, "monotonic", lambda: next(clock, 10_000.0))

    parsed = await _pdf_parser(budget_seconds=10.0).parse(
        b"%PDF",
        mime_type="application/pdf",
        filename="scan.pdf",
    )

    assert len(calls) == 1
    assert parsed.truncated is True
    assert parsed.page_count == 1


def _image_parser(*, limiter: asyncio.Semaphore | None = None) -> TesseractImageOcrParser:
    return TesseractImageOcrParser(
        max_chars=10_000,
        max_bytes=1024,
        timeout_seconds=_TIMEOUT_SECONDS,
        limiter=limiter or asyncio.Semaphore(1),
        tesseract_cmd=None,
    )


async def test_image_ocr_passes_timeout_and_refuses_on_hang(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def _hang(*_args: object, **kwargs: Any) -> dict[str, list[object]]:
        calls.append(kwargs)
        raise RuntimeError("Tesseract process timeout")

    fake_pytesseract = SimpleNamespace(
        pytesseract=SimpleNamespace(tesseract_cmd=""),
        image_to_data=_hang,
        Output=SimpleNamespace(DICT="dict"),
    )
    fake_image = SimpleNamespace(open=lambda _buffer: SimpleNamespace(load=lambda: None))
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)
    monkeypatch.setitem(sys.modules, "PIL", SimpleNamespace(Image=fake_image))
    monkeypatch.setattr(image_ocr_module, "assert_image_decode_within_budget", lambda _data: None)

    with pytest.raises(DocumentParseError, match="timed out"):
        await _image_parser().parse(b"png", mime_type="image/png", filename="scan.png")

    assert calls[0]["timeout"] == _TIMEOUT_SECONDS


async def test_image_ocr_runs_one_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two parallel uploads must queue on the OCR slot, not stampede the CPU."""

    class _Probe:
        def __init__(self) -> None:
            self.active = 0
            self.peak = 0

        def transcribe(self) -> tuple[str, float]:
            self.active += 1
            self.peak = max(self.peak, self.active)
            time.sleep(0.05)
            self.active -= 1
            return "text", 90.0

    probe = _Probe()
    parser = _image_parser()
    monkeypatch.setattr(image_ocr_module, "assert_image_decode_within_budget", lambda _data: None)
    monkeypatch.setattr(parser, "_transcribe_sync", lambda *_args: probe.transcribe())

    await asyncio.gather(
        parser.parse(b"png", mime_type="image/png", filename="a.png"),
        parser.parse(b"png", mime_type="image/png", filename="b.png"),
    )

    assert probe.peak == 1


__all__: list[str] = []
