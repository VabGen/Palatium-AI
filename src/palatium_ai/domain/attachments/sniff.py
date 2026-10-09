# src/palatium_ai/domain/attachments/sniff.py

"""Content-based media type detection (magic bytes) — pure, no I/O (020, 055).

Client-declared MIME is untrusted. After bytes exist, the pipeline calls
:func:`sniff_media_type` and :meth:`AttachmentIntakePolicy.content_matches_declared`
so a renamed executable cannot pass as a PDF.
"""

from __future__ import annotations

from io import BytesIO
from zipfile import BadZipFile, ZipFile

# Sample window for text heuristics — enough for BOM + first line, bounded for cost.
_TEXT_SAMPLE_BYTES = 4096
_ZIP_SNIFF_MEMBER_CAP = 64

# Closed map: magic → registry MIME (must stay ⊆ SUPPORTED_MEDIA_TYPES keys).
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_PDF_MAGIC = b"%PDF"
_ZIP_LOCAL = b"PK\x03\x04"
_ZIP_EMPTY = b"PK\x05\x06"


def sniff_media_type(data: bytes) -> str | None:
    """Return a supported MIME when magic bytes identify the payload, else None.

    ``None`` means "undetected" — not "allowed". Callers decide whether an
    undetected payload may proceed (text types) or must be refused (binary).
    """
    if not data:
        return None
    if data.startswith(_PDF_MAGIC):
        return "application/pdf"
    if data.startswith(_PNG_MAGIC):
        return "image/png"
    if data.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if _is_webp(data):
        return "image/webp"
    if data.startswith((_ZIP_LOCAL, _ZIP_EMPTY)):
        return _sniff_office_zip(data)
    if _looks_like_text(data):
        # Ambiguous among text/plain, text/markdown, text/csv — caller keeps declared
        # when it is a text/* registry member (content_matches_declared).
        return "text/*"
    return None


def _is_webp(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def _sniff_office_zip(data: bytes) -> str | None:
    """Distinguish DOCX (word/) from other OOXML packages without full inflate."""
    try:
        with ZipFile(BytesIO(data)) as archive:
            names = {info.filename.replace("\\", "/") for info in archive.infolist()[:_ZIP_SNIFF_MEMBER_CAP]}
    except (BadZipFile, OSError):
        return None
    if "[Content_Types].xml" not in names and not any(n.endswith("[Content_Types].xml") for n in names):
        # Still OOXML-ish if word/ exists; Content_Types is the strong signal.
        if any(n.startswith("word/") for n in names):
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return None
    if any(n.startswith("word/") for n in names):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if any(n.startswith("xl/") for n in names):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if any(n.startswith("ppt/") for n in names):
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    return None


def _looks_like_text(data: bytes) -> bool:
    """Cheap UTF-8 / printable heuristic for text/* allowlist members."""
    sample = data[:_TEXT_SAMPLE_BYTES]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    # Reject high binary ratio even when UTF-8-decodable (rare but hostile).
    printable = sum(1 for b in sample if b in (9, 10, 13) or 32 <= b < 127 or b >= 128)
    return printable / max(len(sample), 1) >= 0.85


__all__ = ["sniff_media_type"]
