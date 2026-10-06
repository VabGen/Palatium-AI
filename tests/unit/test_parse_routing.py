# tests/unit/test_parse_routing.py

"""Deterministic attachment parse / chat-text routing (domain policy)."""

from __future__ import annotations

import pytest

from palatium_ai.domain.attachments.parse_routing import (
    AUTO_ATTACH_CHARS,
    INTENT_TEXT_LIMIT,
    choose_parse_strategy,
    ocr_text_is_usable,
    route_text_from_chat,
    text_layer_is_sufficient,
)

_MAX_BYTES = 50 * 1024 * 1024


def test_ocr_text_is_usable_quality_gate() -> None:
    assert ocr_text_is_usable("Invoice total due 1 200 BYN") is True
    assert ocr_text_is_usable("") is False
    assert ocr_text_is_usable("ab") is False
    assert ocr_text_is_usable("@@@@@@@@@@@@") is False


def test_ocr_text_is_usable_escalates_on_low_tesseract_confidence() -> None:
    """Latin gibberish from Cyrillic handwriting is printable but low-confidence."""
    junk = "Lede ve ne Cale RTE SOLD ge SOON"
    assert ocr_text_is_usable(junk) is True  # printable-only would wrongly keep
    assert ocr_text_is_usable(junk, mean_confidence=28.0) is False
    assert ocr_text_is_usable(junk, mean_confidence=72.0) is True


def test_text_layer_sufficient_uses_avg_chars_per_page() -> None:
    assert text_layer_is_sufficient(total_chars=2000, page_count=10) is True
    assert text_layer_is_sufficient(total_chars=1000, page_count=10) is False
    assert text_layer_is_sufficient(total_chars=0, page_count=1) is False
    assert text_layer_is_sufficient(total_chars=500, page_count=0) is False


def test_choose_image_prefers_ocr_primary() -> None:
    decision = choose_parse_strategy(mime_type="image/png", model_supports_vision=True)
    assert decision.strategy == "ocr"
    assert decision.reason == "image_ocr_primary"


def test_choose_image_stays_ocr_without_vision() -> None:
    decision = choose_parse_strategy(mime_type="image/jpeg", model_supports_vision=False)
    assert decision.strategy == "ocr"


def test_choose_pdf_probe_pending_without_layer_stats() -> None:
    decision = choose_parse_strategy(mime_type="application/pdf", model_supports_vision=True)
    assert decision.strategy == "text_layer"
    assert decision.reason == "pdf_probe_pending"


def test_choose_pdf_text_layer_ok() -> None:
    decision = choose_parse_strategy(
        mime_type="application/pdf",
        model_supports_vision=True,
        text_layer_chars=5000,
        page_count=5,
    )
    assert decision.strategy == "text_layer"
    assert decision.reason == "pdf_text_layer_ok"


def test_choose_pdf_scan_routes_to_ocr_first() -> None:
    decision = choose_parse_strategy(
        mime_type="application/pdf",
        model_supports_vision=True,
        text_layer_chars=10,
        page_count=5,
    )
    assert decision.strategy == "ocr"
    assert decision.reason == "pdf_scan_ocr_first"


def test_choose_pdf_scan_routes_to_ocr_without_vision() -> None:
    decision = choose_parse_strategy(
        mime_type="application/pdf",
        model_supports_vision=False,
        text_layer_chars=10,
        page_count=5,
    )
    assert decision.strategy == "ocr"


def test_choose_docx_and_plain_are_text_layer() -> None:
    assert choose_parse_strategy(mime_type="text/plain", model_supports_vision=False).strategy == "text_layer"
    assert (
        choose_parse_strategy(
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            model_supports_vision=False,
        ).strategy
        == "text_layer"
    )


def test_choose_unknown_mime_refuses() -> None:
    decision = choose_parse_strategy(mime_type="application/octet-stream", model_supports_vision=False)
    assert decision.strategy == "refuse"


@pytest.mark.parametrize(
    "length,route",
    (
        (0, "text_only"),
        (AUTO_ATTACH_CHARS, "text_only"),
        (AUTO_ATTACH_CHARS + 1, "attach_text"),
        (INTENT_TEXT_LIMIT, "attach_text"),
        (INTENT_TEXT_LIMIT + 1, "attach_text"),
    ),
)
def test_route_text_from_chat_by_length(length: int, route: str) -> None:
    decision = route_text_from_chat("x" * length, max_attachment_bytes=_MAX_BYTES)
    assert decision.route == route


def test_route_text_from_chat_refuses_over_byte_cap() -> None:
    # Cyrillic is 2 bytes/char in UTF-8 → fewer chars still blow the byte budget.
    text = "я" * (_MAX_BYTES // 2 + 1)
    decision = route_text_from_chat(text, max_attachment_bytes=_MAX_BYTES)
    assert decision.route == "refuse_too_large"
