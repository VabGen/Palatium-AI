# src/palatium_ai/domain/attachments/active_content.py

"""OOXML active-content probes (macros, OLE embeddings) — pure, no I/O beyond bytes (020)."""

from __future__ import annotations

from io import BytesIO
from zipfile import BadZipFile, ZipFile

_VBA_PROJECT_BASENAME = "vbaproject.bin"
_EMBEDDING_PREFIXES = (
    "word/embeddings/",
    "ppt/embeddings/",
    "xl/embeddings/",
)


def ooxml_contains_active_content(data: bytes) -> bool:
    """True when an OOXML package carries VBA or OLE ``.bin`` embeddings.

    Covers DOCX / PPTX / XLSX. Corrupt zips return False so the parser can still
    emit ``parse_failed``.
    """
    try:
        with ZipFile(BytesIO(data)) as archive:
            for entry in archive.namelist():
                normalized = entry.replace("\\", "/").lstrip("/").lower()
                basename = normalized.rsplit("/", 1)[-1]
                if basename == _VBA_PROJECT_BASENAME:
                    return True
                if basename.endswith(".bin") and any(normalized.startswith(prefix) for prefix in _EMBEDDING_PREFIXES):
                    return True
    except BadZipFile:
        return False
    return False


def docx_contains_active_content(data: bytes) -> bool:
    """Backward-compatible alias for DOCX callers."""
    return ooxml_contains_active_content(data)


__all__ = ["docx_contains_active_content", "ooxml_contains_active_content"]
