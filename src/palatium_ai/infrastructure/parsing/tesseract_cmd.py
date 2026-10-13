# src/palatium_ai/infrastructure/parsing/tesseract_cmd.py

"""Resolve the Tesseract binary once at wiring time (no per-page PATH guesses).

``ATTACHMENTS_TESSERACT_CMD`` wins; otherwise PATH + OS defaults. Returns ``None``
when no binary is reachable so the factory can skip local OCR instead of raising
``TesseractNotFoundError`` on every PDF page (Windows host without Docker).
"""

from __future__ import annotations

import platform
import shutil

from pathlib import Path

# Debian/Ubuntu package ``tesseract-ocr`` (Docker WITH_ATTACHMENTS=1).
_LINUX_DEFAULT = "/usr/bin/tesseract"
# UB-Mannheim / winget installer layouts on Windows.
_WINDOWS_DEFAULTS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def resolve_tesseract_cmd(configured: str | None = None) -> str | None:
    """Return an absolute path to ``tesseract``, or ``None`` if nothing is usable."""
    candidates: list[str] = []
    override = (configured or "").strip().strip('"').strip("'")
    if override:
        candidates.append(override)

    which = shutil.which("tesseract")
    if which:
        candidates.append(which)

    system = platform.system()
    if system == "Windows":
        candidates.extend(_WINDOWS_DEFAULTS)
    elif system == "Linux":
        candidates.append(_LINUX_DEFAULT)

    seen: set[str] = set()
    for raw in candidates:
        if raw in seen:
            continue
        seen.add(raw)
        path = Path(raw)
        if path.is_file():
            return str(path)
    return None


__all__ = ["resolve_tesseract_cmd"]
