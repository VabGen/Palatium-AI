# tests/unit/test_attachment_extracted_pii.py

"""G06: PII tagging, masking, reject tiers and secret blocking on extracted text."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from palatium_ai.application.services.attachment_pipeline import AttachmentPipeline
from palatium_ai.domain.attachments import Attachment, AttachmentLimits
from palatium_ai.domain.attachments.pii_policy import apply_attachment_pii_policy
from palatium_ai.domain.ports.blob_store import BlobStat
from palatium_ai.domain.ports.document_parser import ParsedDocument, ParsedPage
from palatium_ai.domain.ports.scanner import ScanVerdict


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
    def __init__(self, text: str) -> None:
        self._text = text

    def supports(self, mime_type: str) -> bool:
        return mime_type == "text/plain"

    async def parse(self, data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
        _ = data, mime_type, filename
        return ParsedDocument(pages=(ParsedPage(number=1, text=self._text),), extraction_source="text_layer")


def _attachment() -> Attachment:
    return Attachment(
        id=uuid4(),
        user_id="u1",
        thread_id="th-1",
        filename="note.txt",
        mime_type="text/plain",
        size_bytes=64,
        mode="attach",
        status="uploaded",
        blob_key="attachments/x",
        created_at=datetime.now(UTC),
    )


def test_pii_policy_tag_mask_reject() -> None:
    text = "reach me at bob@example.com"
    tagged = apply_attachment_pii_policy(text, mode="tag")
    assert tagged.contains_pii
    assert not tagged.refuse
    masked = apply_attachment_pii_policy(text, mode="mask")
    assert masked.contains_pii
    assert masked.masked_text is not None
    assert "bob@example.com" not in masked.masked_text
    assert "[EMAIL]" in masked.masked_text
    rejected = apply_attachment_pii_policy(text, mode="reject")
    assert rejected.refuse


@pytest.mark.asyncio()
async def test_pipeline_tags_contains_pii_without_blocking() -> None:
    pipeline = AttachmentPipeline(
        blob_store=_Blob(b"contact bob@example.com"),
        malware_scanner=_Scanner(),
        document_parser=_Parser("reach me at bob@example.com"),
        pii_policy="tag",
    )
    outcome = await pipeline.run(_attachment(), limits=AttachmentLimits())
    assert outcome.admitted
    assert outcome.content is not None
    assert outcome.content.contains_pii is True
    assert "bob@example.com" in outcome.content.safe_text


@pytest.mark.asyncio()
async def test_pipeline_masks_pii_in_safe_text() -> None:
    pipeline = AttachmentPipeline(
        blob_store=_Blob(b"contact bob@example.com"),
        malware_scanner=_Scanner(),
        document_parser=_Parser("reach me at bob@example.com"),
        pii_policy="mask",
    )
    outcome = await pipeline.run(_attachment(), limits=AttachmentLimits())
    assert outcome.admitted
    assert outcome.content is not None
    assert outcome.content.contains_pii is True
    assert "bob@example.com" not in outcome.content.safe_text
    assert "[EMAIL]" in outcome.content.safe_text


@pytest.mark.asyncio()
async def test_pipeline_rejects_pii_under_reject_policy() -> None:
    pipeline = AttachmentPipeline(
        blob_store=_Blob(b"contact bob@example.com"),
        malware_scanner=_Scanner(),
        document_parser=_Parser("reach me at bob@example.com"),
        pii_policy="reject",
    )
    outcome = await pipeline.run(_attachment(), limits=AttachmentLimits())
    assert outcome.status == "rejected"
    assert outcome.rejection_reason == "pii_detected"


@pytest.mark.asyncio()
async def test_pipeline_refuses_extracted_secret_pattern() -> None:
    secret_text = "backup key sk-abcdefghijklmnopqrstuvwxyz"
    pipeline = AttachmentPipeline(
        blob_store=_Blob(secret_text.encode()),
        malware_scanner=_Scanner(),
        document_parser=_Parser(secret_text),
    )
    outcome = await pipeline.run(_attachment(), limits=AttachmentLimits())
    assert outcome.status == "rejected"
    assert outcome.rejection_reason == "parse_failed"
