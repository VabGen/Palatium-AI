# tests/unit/test_ocr_timeout_default.py

"""P2.16: Vision OCR default timeout is 30s."""

from __future__ import annotations

from palatium_ai.core.config.attachments import AttachmentConfig


def test_image_ocr_timeout_default_is_30() -> None:
    cfg = AttachmentConfig()
    assert cfg.image_ocr_timeout_seconds == 30.0
