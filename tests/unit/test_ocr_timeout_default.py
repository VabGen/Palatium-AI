# tests/unit/test_ocr_timeout_default.py

"""P2.16: Vision OCR default timeout is 30s."""

from __future__ import annotations

from palatium_ai.core.config.attachments import AttachmentConfig


def test_image_ocr_timeout_default_is_30() -> None:
    cfg = AttachmentConfig()
    assert cfg.image_ocr_timeout_seconds == 30.0


def test_tesseract_page_timeout_default_is_30() -> None:
    """90 s per page wasted a whole document on one timed-out page (080).

    The page timeout is a per-page kill, not the document budget: a page that has
    not produced text in 30 s is routed to Vision alone while the other pages keep
    their Tesseract output, so the default must stay small.
    """
    cfg = AttachmentConfig()
    assert cfg.tesseract_timeout_seconds == 30.0
