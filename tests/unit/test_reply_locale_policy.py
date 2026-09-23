"""ReplyLocalePolicy — script detection + sticky prior (no phrase lists)."""

from __future__ import annotations

from palatium_ai.domain.content import (
    CodeBlock,
    ContentDocument,
    DocumentMeta,
    ParagraphBlock,
)
from palatium_ai.domain.policies.locale import ReplyLocalePolicy


def test_cyrillic_user_text_resolves_ru() -> None:
    locale = ReplyLocalePolicy.resolve(user_text="Какие планы на сегодня")
    assert locale == "ru-RU"


def test_sticky_prior_keeps_locale_on_weak_ack() -> None:
    locale = ReplyLocalePolicy.resolve(
        user_text="ok",
        prior_locale="ru-RU",
    )
    assert locale == "ru-RU"


def test_latin_followup_switches_from_cyrillic_prior() -> None:
    locale = ReplyLocalePolicy.resolve(
        user_text="Sounds like a great plan for tomorrow afternoon jogging",
        prior_locale="ru-RU",
    )
    assert locale == "en-US"


def test_cyrillic_followup_keeps_russian_prior() -> None:
    """Regression: social follow-up must not snap to English."""
    locale = ReplyLocalePolicy.resolve(
        user_text="а я планирую завтра днем выйти на пробежку",
        prior_locale="ru-RU",
    )
    assert locale == "ru-RU"


def test_code_fence_ignored_for_script() -> None:
    locale = ReplyLocalePolicy.resolve(
        user_text="объясни\n```python\nprint('hello world this is english code')\n```",
        prior_locale="ru-RU",
    )
    assert locale == "ru-RU"


def test_prose_mismatch_detects_english_on_ru_pin() -> None:
    assert not ReplyLocalePolicy.prose_matches_locale(
        "Sounds like a great plan! Enjoy your run tomorrow afternoon.",
        "ru-RU",
    )


def test_document_prose_skips_code_blocks() -> None:
    doc = ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title="Ответ",
        blocks=(
            ParagraphBlock(type="paragraph", text="Вот пример:"),
            CodeBlock(type="code", language="python", content="print('hello world example')"),
        ),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=()),
    )
    prose = ReplyLocalePolicy.document_prose(doc)
    assert "Вот пример" in prose
    assert "hello world" not in prose
    assert ReplyLocalePolicy.prose_matches_locale(prose, "ru-RU")


def test_normalize_accepts_language_only() -> None:
    assert ReplyLocalePolicy.normalize("ru") == "ru"
    assert ReplyLocalePolicy.normalize("en-us") == "en-US"
    assert ReplyLocalePolicy.normalize("") is None
