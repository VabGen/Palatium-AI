# tests/unit/test_tesseract_cmd.py

"""Binary resolution for local Tesseract OCR (wiring-time, not per-page)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from palatium_ai.infrastructure.parsing.tesseract_cmd import resolve_tesseract_cmd

if TYPE_CHECKING:
    import pytest


def test_resolve_prefers_configured_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = tmp_path / "tesseract.exe"
    binary.write_bytes(b"")
    monkeypatch.setattr("palatium_ai.infrastructure.parsing.tesseract_cmd.shutil.which", lambda _: None)
    assert resolve_tesseract_cmd(str(binary)) == str(binary)


def test_resolve_ignores_invalid_override_and_uses_which(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = tmp_path / "tesseract"
    real.write_bytes(b"")
    monkeypatch.setattr(
        "palatium_ai.infrastructure.parsing.tesseract_cmd.shutil.which",
        lambda _: str(real),
    )
    assert resolve_tesseract_cmd(str(tmp_path / "missing.exe")) == str(real)


def test_resolve_returns_none_when_nothing_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("palatium_ai.infrastructure.parsing.tesseract_cmd.shutil.which", lambda _: None)
    monkeypatch.setattr(
        "palatium_ai.infrastructure.parsing.tesseract_cmd.platform.system",
        lambda: "Linux",
    )
    monkeypatch.setattr(
        "palatium_ai.infrastructure.parsing.tesseract_cmd._LINUX_DEFAULT",
        "/nonexistent/tesseract",
    )
    assert resolve_tesseract_cmd(None) is None
    assert resolve_tesseract_cmd("  ") is None


def test_factory_skips_local_ocr_when_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing binary must not wire Tesseract parsers (avoids per-page TesseractNotFoundError)."""
    from types import SimpleNamespace

    from palatium_ai.core.config.attachments import AttachmentConfig
    from palatium_ai.core.config.llm.gateway import GatewayLLMConfig
    from palatium_ai.infrastructure.parsing.factory import build_document_parser

    monkeypatch.setattr(
        "palatium_ai.infrastructure.parsing.factory.resolve_tesseract_cmd",
        lambda _configured=None: None,
    )
    settings = SimpleNamespace(
        attachments=AttachmentConfig(
            _env_file=None,
            image_ocr_backend="auto",
            image_ocr_model="tier-mid",
        ),
        llm=SimpleNamespace(gateway=GatewayLLMConfig(_env_file=None)),  # type: ignore[call-arg]
    )
    parser = build_document_parser(settings)  # type: ignore[arg-type]
    assert getattr(parser, "_pdf_ocr", "missing") is None
    # Vision escalate still available for images when gateway + model are set.
    assert parser.supports("image/png")
