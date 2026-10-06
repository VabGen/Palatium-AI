"""AckReplyPolicy — deterministic social reply (P0.1 fast path)."""

from palatium_ai.domain.policies import AckReplyPolicy


def test_ack_reply_ru_locale() -> None:
    doc = AckReplyPolicy.build_document(response_locale="ru-RU", confidence=0.95)
    assert doc.locale == "ru-RU"
    assert doc.title == "Здравствуйте!"
    assert doc.blocks[0].type == "paragraph"
    assert "помочь" in doc.blocks[0].text.lower()
    assert doc.meta.confidence == 0.95
    assert doc.meta.requires_review is False


def test_ack_reply_en_fallback_for_unknown_lang() -> None:
    doc = AckReplyPolicy.build_document(response_locale="xx-YY")
    assert doc.title == "Hello!"
    assert doc.locale == "xx-YY"


def test_ack_reply_und_keeps_und_locale() -> None:
    doc = AckReplyPolicy.build_document(response_locale="und")
    assert doc.locale == "und"
    assert doc.title == "Hello!"
