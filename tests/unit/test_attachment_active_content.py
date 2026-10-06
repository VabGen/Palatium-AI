# tests/unit/test_attachment_active_content.py

"""G05: DOCX macro / OLE embedding refusal (domain + pipeline)."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest

from palatium_ai.application.services.attachment_pipeline import AttachmentPipeline
from palatium_ai.domain.attachments import Attachment, AttachmentLimits
from palatium_ai.domain.attachments.active_content import (
    docx_contains_active_content,
    ooxml_contains_active_content,
)
from palatium_ai.domain.ports.blob_store import BlobStat
from palatium_ai.domain.ports.document_parser import ParsedDocument, ParsedPage
from palatium_ai.domain.ports.scanner import ScanVerdict

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _minimal_docx(*extra: tuple[str, bytes]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
        for path, payload in extra:
            archive.writestr(path, payload)
    return buffer.getvalue()


def test_docx_clean_package_has_no_active_content() -> None:
    assert not docx_contains_active_content(_minimal_docx())


def test_docx_vba_project_is_active_content() -> None:
    assert docx_contains_active_content(_minimal_docx(("word/vbaProject.bin", b"vba")))


def test_docx_embedding_bin_is_active_content() -> None:
    assert docx_contains_active_content(_minimal_docx(("word/embeddings/oleObject1.bin", b"\x00\x01")))


def test_pptx_vba_project_is_active_content() -> None:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("ppt/slides/slide1.xml", "<p:sld/>")
        archive.writestr("ppt/vbaProject.bin", b"vba")
    assert ooxml_contains_active_content(buffer.getvalue())


def test_xlsx_embedding_bin_is_active_content() -> None:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/embeddings/oleObject1.bin", b"\x00\x01")
    assert ooxml_contains_active_content(buffer.getvalue())


class _Blob:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def stat(self, key: str) -> BlobStat:
        return BlobStat(key=key, size_bytes=len(self._data), content_type=_DOCX_MIME)

    async def read_bytes(self, key: str) -> bytes:
        _ = key
        return self._data


class _Scanner:
    async def scan(self, data: bytes, *, filename: str) -> ScanVerdict:
        return ScanVerdict(clean=True, engine="test", scanned_bytes=len(data), reason=filename)


class _Parser:
    def supports(self, mime_type: str) -> bool:
        return mime_type == _DOCX_MIME

    async def parse(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
        _ = data, mime_type, filename
        return ParsedDocument(pages=(ParsedPage(number=1, text="ok"),), extraction_source="text_layer")


@pytest.mark.asyncio()
async def test_pipeline_refuses_docx_with_macros_before_parse() -> None:
    pipeline = AttachmentPipeline(
        blob_store=_Blob(_minimal_docx(("word/vbaProject.bin", b"x"))),
        malware_scanner=_Scanner(),
        document_parser=_Parser(),
    )
    attachment = Attachment(
        id=uuid4(),
        user_id="u1",
        thread_id="th-1",
        filename="doc.docx",
        mime_type=_DOCX_MIME,
        size_bytes=128,
        mode="attach",
        status="uploaded",
        blob_key="attachments/x",
        created_at=datetime.now(UTC),
    )
    outcome = await pipeline.run(attachment, limits=AttachmentLimits())
    assert outcome.status == "rejected"
    assert outcome.rejection_reason == "active_content"
