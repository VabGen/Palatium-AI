"""AttachmentReadService: RBAC, cache, lazy parse, size ceiling (020, 070)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from palatium_ai.application.services.attachment_read_service import AttachmentReadService
from palatium_ai.domain.attachments import (
    Attachment,
    AttachmentContent,
    AttachmentContentMetadata,
    AttachmentNotFoundError,
    AttachmentReadRequest,
    AttachmentScanSummary,
    AttachmentTooLargeError,
)
from palatium_ai.domain.attachments.policies import DEFAULT_ATTACHMENT_LIMITS
from palatium_ai.domain.ports.document_parser import ParsedDocument, ParsedPage


class _FakeRepo:
    def __init__(self, rows: dict[object, Attachment]) -> None:
        self.rows = rows
        self.updates: list[dict[str, object]] = []

    async def get(self, attachment_id, *, user_id: str):
        row = self.rows.get(attachment_id)
        if row is None or row.user_id != user_id:
            return None
        return row

    async def update_extraction_state(self, attachment_id, *, user_id: str, **kwargs):
        self.updates.append({"id": attachment_id, "user_id": user_id, **kwargs})
        row = self.rows[attachment_id]
        updated = row.model_copy(update=kwargs)
        self.rows[attachment_id] = updated
        return updated


class _FakeBlob:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    async def read_bytes(self, key: str) -> bytes:
        from palatium_ai.domain.ports.blob_store import BlobNotFoundError

        if key not in self.objects:
            raise BlobNotFoundError(key)
        return self.objects[key]

    async def write_bytes(self, key: str, data: bytes, *, content_type: str = "") -> None:
        self.objects[key] = data


class _FakePipeline:
    def __init__(self, content: AttachmentContent | None) -> None:
        self.content = content
        self.calls = 0

    async def reparse_bytes(self, attachment, data, *, mime_type: str):
        self.calls += 1
        return self.content


_NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
_LIMITS = DEFAULT_ATTACHMENT_LIMITS


def _row(**overrides: object) -> Attachment:
    payload: dict[str, object] = {
        "id": uuid4(),
        "user_id": "owner",
        "thread_id": "t1",
        "filename": "scan.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 1024,
        "blob_key": "attachments/x",
        "mode": "attach",
        "status": "ready",
        "created_at": _NOW,
    }
    payload.update(overrides)
    return Attachment(**payload)  # type: ignore[arg-type]


def _content(text: str, *, engine: str | None = "tesseract") -> AttachmentContent:
    return AttachmentContent(
        pages=(ParsedPage(number=1, text=text),) if text else (),
        scan=AttachmentScanSummary(action="allow"),
        safe_text=text,
        page_count=1 if text else 0,
        metadata=AttachmentContentMetadata(
            ocr_engine=engine if engine in ("tesseract", "llm_vision") else None,
            extraction_source="ocr" if engine == "tesseract" else ("vision" if engine == "llm_vision" else "none"),
        ),
    )


@pytest.mark.asyncio()
async def test_foreign_user_gets_not_found() -> None:
    row = _row()
    svc = AttachmentReadService(
        repository=_FakeRepo({row.id: row}),  # type: ignore[arg-type]
        blob_store=_FakeBlob({}),  # type: ignore[arg-type]
        pipeline=_FakePipeline(None),  # type: ignore[arg-type]
        limits=_LIMITS,
    )
    with pytest.raises(AttachmentNotFoundError):
        await svc.read(AttachmentReadRequest(attachment_id=row.id, user_id="other"))


@pytest.mark.asyncio()
async def test_cached_path_skips_parser() -> None:
    row = _row(derived_text_key="attachments/x.text.json")
    content = _content("cached body")
    blob = _FakeBlob({row.derived_text_key: content.model_dump_json().encode()})
    pipeline = _FakePipeline(_content("should not run"))
    svc = AttachmentReadService(
        repository=_FakeRepo({row.id: row}),  # type: ignore[arg-type]
        blob_store=blob,  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        limits=_LIMITS,
    )
    result = await svc.read(AttachmentReadRequest(attachment_id=row.id, user_id="owner"))
    assert result.text == "cached body"
    assert result.ocr_cached is True
    assert result.ocr_applied is False
    assert pipeline.calls == 0


@pytest.mark.asyncio()
async def test_lazy_path_write_through() -> None:
    row = _row(blob_key="attachments/raw")
    repo = _FakeRepo({row.id: row})
    blob = _FakeBlob({"attachments/raw": b"%PDF"})
    pipeline = _FakePipeline(_content("ocr text", engine="llm_vision"))
    svc = AttachmentReadService(
        repository=repo,  # type: ignore[arg-type]
        blob_store=blob,  # type: ignore[arg-type]
        pipeline=pipeline,  # type: ignore[arg-type]
        limits=_LIMITS,
    )
    result = await svc.read(AttachmentReadRequest(attachment_id=row.id, user_id="owner"))
    assert result.text == "ocr text"
    assert result.ocr_applied is True
    assert result.ocr_engine == "llm_vision"
    assert result.ocr_cached is False
    assert repo.updates
    assert any(k.startswith("attachments/") and k.endswith(".text.json") for k in blob.objects)


@pytest.mark.asyncio()
async def test_lazy_empty_returns_notice() -> None:
    row = _row(blob_key="attachments/raw")
    svc = AttachmentReadService(
        repository=_FakeRepo({row.id: row}),  # type: ignore[arg-type]
        blob_store=_FakeBlob({"attachments/raw": b"%PDF"}),  # type: ignore[arg-type]
        pipeline=_FakePipeline(None),  # type: ignore[arg-type]
        limits=_LIMITS,
    )
    result = await svc.read(AttachmentReadRequest(attachment_id=row.id, user_id="owner"))
    assert result.text == ""
    assert result.notice is not None
    assert result.extract_status == "empty"


@pytest.mark.asyncio()
async def test_size_ceiling() -> None:
    row = _row(size_bytes=60 * 1024 * 1024)
    svc = AttachmentReadService(
        repository=_FakeRepo({row.id: row}),  # type: ignore[arg-type]
        blob_store=_FakeBlob({}),  # type: ignore[arg-type]
        pipeline=_FakePipeline(None),  # type: ignore[arg-type]
        limits=_LIMITS,
    )
    with pytest.raises(AttachmentTooLargeError):
        await svc.read(AttachmentReadRequest(attachment_id=row.id, user_id="owner"))


def test_parsed_document_unused_import_guard() -> None:
    # Keep ParsedDocument import honest for future parser fakes.
    assert ParsedDocument(pages=(), extraction_source="none").text == ""
