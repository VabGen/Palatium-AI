# tests/unit/test_attachment_parse_metric.py

"""attachment parse provenance metric (040)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from palatium_ai.application.services.attachment_pipeline import AttachmentPipeline
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.attachments import Attachment, AttachmentLimits
from palatium_ai.domain.ports.blob_store import BlobStat
from palatium_ai.domain.ports.document_parser import ParsedDocument, ParsedPage
from palatium_ai.domain.ports.scanner import ScanVerdict

pytestmark = pytest.mark.asyncio


class _Blob:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def stat(self, key: str) -> BlobStat:
        return BlobStat(key=key, size_bytes=len(self._data), content_type="text/plain")

    async def read_bytes(self, key: str) -> bytes:
        _ = key
        return self._data


class _Scanner:
    async def scan(self, data: bytes, *, filename: str) -> ScanVerdict:
        return ScanVerdict(clean=True, engine="test", scanned_bytes=len(data), reason=filename)


class _Parser:
    def supports(self, mime_type: str) -> bool:
        return mime_type == "text/plain"

    async def parse(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
        _ = mime_type, filename
        return ParsedDocument(
            pages=(ParsedPage(number=1, text=data.decode("utf-8")),),
            extraction_source="text_layer",
        )


async def test_pipeline_records_extraction_source_metric() -> None:
    before = agent_metrics.attachment_parse_count("text_layer", "text")
    pipeline = AttachmentPipeline(
        blob_store=_Blob(b"hello attachment"),
        malware_scanner=_Scanner(),
        document_parser=_Parser(),
    )
    attachment = Attachment(
        id=uuid4(),
        user_id="u1",
        thread_id="th-1",
        filename="a.txt",
        mime_type="text/plain",
        size_bytes=16,
        mode="attach",
        status="uploaded",
        blob_key="attachments/x",
        created_at=datetime.now(UTC),
    )
    outcome = await pipeline.run(attachment, limits=AttachmentLimits())
    assert outcome.admitted
    assert agent_metrics.attachment_parse_count("text_layer", "text") == before + 1
