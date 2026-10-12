"""Domain contracts for ``platform.read_attachment`` (010, 070)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from pydantic import ValidationError

from palatium_ai.domain.attachments import (
    AttachmentReadRequest,
    AttachmentReadResult,
    AttachmentTooLargeError,
    extraction_source_to_extract_status,
    extraction_source_to_ocr_engine,
)


def test_read_request_defaults() -> None:
    req = AttachmentReadRequest(attachment_id=uuid4(), user_id="u1")
    assert req.offset == 0
    assert req.max_chars == 32_000
    assert req.force_ocr is False


def test_read_request_rejects_empty_user() -> None:
    with pytest.raises(ValidationError):
        AttachmentReadRequest(attachment_id=uuid4(), user_id="")


def test_extraction_source_mapping() -> None:
    assert extraction_source_to_ocr_engine("ocr") == "tesseract"
    assert extraction_source_to_ocr_engine("vision") == "llm_vision"
    assert extraction_source_to_ocr_engine("text_layer") is None
    assert extraction_source_to_extract_status("ocr", text_chars=10) == "ocr_ok"
    assert extraction_source_to_extract_status("vision", text_chars=10) == "vision_ok"
    assert extraction_source_to_extract_status("text_layer", text_chars=10) == "text_ok"
    assert extraction_source_to_extract_status("ocr", text_chars=0) == "empty"


def test_read_result_notice_path() -> None:
    result = AttachmentReadResult(
        attachment_id=uuid4(),
        filename="scan.pdf",
        mime_type="application/pdf",
        text="",
        extract_status="empty",
        notice="OCR and Vision unavailable",
    )
    assert result.ocr_applied is False
    assert result.notice is not None


def test_too_large_error_carries_sizes() -> None:
    aid = uuid4()
    exc = AttachmentTooLargeError(aid, size_bytes=60_000_000, max_size_bytes=50_000_000)
    assert exc.attachment_id == aid
    assert exc.size_bytes == 60_000_000
    assert "read ceiling" in str(exc)
