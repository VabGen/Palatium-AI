# tests/unit/test_attachment_mime_sniff.py

"""Magic-byte sniff + content_matches_declared (W1 G01)."""

from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from palatium_ai.domain.attachments.policies import AttachmentIntakePolicy
from palatium_ai.domain.attachments.sniff import sniff_media_type


def _xlsx_bytes() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
    return buffer.getvalue()


def _docx_bytes() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


def test_sniff_pdf_magic() -> None:
    assert sniff_media_type(b"%PDF-1.7\n%") == "application/pdf"


def test_sniff_png_magic() -> None:
    assert sniff_media_type(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8) == "image/png"


def test_sniff_jpeg_magic() -> None:
    assert sniff_media_type(b"\xff\xd8\xff\xe0" + b"\x00" * 16) == "image/jpeg"


def test_sniff_webp_magic() -> None:
    assert sniff_media_type(b"RIFF" + (20).to_bytes(4, "little") + b"WEBP") == "image/webp"


def test_sniff_xlsx_ooxml() -> None:
    assert sniff_media_type(_xlsx_bytes()) == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_content_matches_declared_xlsx_ok() -> None:
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    decision = AttachmentIntakePolicy.content_matches_declared(
        declared_mime=mime,
        detected_mime=mime,
        filename="table.xlsx",
    )
    assert decision.allowed


def test_sniff_docx_ooxml() -> None:
    assert sniff_media_type(_docx_bytes()) == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _pptx_bytes() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("ppt/slides/slide1.xml", "<p:sld/>")
    return buffer.getvalue()


def test_sniff_pptx_ooxml() -> None:
    assert (
        sniff_media_type(_pptx_bytes()) == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )


def test_sniff_utf8_text_sentinel() -> None:
    assert sniff_media_type(b"hello world\nline two") == "text/*"


def test_sniff_rejects_null_binary_as_text() -> None:
    assert sniff_media_type(b"abc\x00def" + b"\xff" * 32) is None


def test_content_matches_declared_pdf_ok() -> None:
    decision = AttachmentIntakePolicy.content_matches_declared(
        declared_mime="application/pdf",
        detected_mime="application/pdf",
        filename="doc.pdf",
    )
    assert decision.allowed


def test_content_matches_declared_mismatch() -> None:
    decision = AttachmentIntakePolicy.content_matches_declared(
        declared_mime="application/pdf",
        detected_mime="image/png",
        filename="doc.pdf",
    )
    assert decision.refused
    assert decision.reason == "mime_mismatch"


def test_content_matches_text_subtype_with_text_sentinel() -> None:
    decision = AttachmentIntakePolicy.content_matches_declared(
        declared_mime="text/csv",
        detected_mime="text/*",
        filename="table.csv",
    )
    assert decision.allowed


def test_content_matches_binary_undetected_fails_closed() -> None:
    decision = AttachmentIntakePolicy.content_matches_declared(
        declared_mime="application/pdf",
        detected_mime=None,
        filename="doc.pdf",
    )
    assert decision.reason == "mime_mismatch"
