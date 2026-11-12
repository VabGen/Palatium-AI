"""HitlCopyPolicy — locale-aware quality / MCP card chrome."""

from __future__ import annotations

from palatium_ai.domain.hitl.copy import HitlCopyPolicy


def test_review_copy_russian() -> None:
    copy = HitlCopyPolicy.review(locale="ru-RU", confidence=0.5)
    assert copy.title == "Требуется проверка"
    assert "уверенность 0.50" in copy.body
    labels = {opt.action_id: opt.label for opt in copy.options}
    assert labels["approve"] == "Подтвердить"
    assert labels["reject"] == "Отклонить и переработать"
    assert copy.options[0].icon == "check"


def test_review_copy_english_default() -> None:
    copy = HitlCopyPolicy.review(locale="en-US", confidence=0.5, document_title="Draft")
    assert copy.title == "Draft"
    labels = {opt.action_id: opt.label for opt in copy.options}
    assert labels["approve"] == "Approve"


def test_review_copy_und_locale_follows_cyrillic_prose() -> None:
    """``und`` + Russian answer prose must not mint English quality-gate chrome."""
    copy = HitlCopyPolicy.review(
        locale="und",
        confidence=0.5,
        prose_hint="Обзор предоставленных документов",
    )
    assert copy.title == "Требуется проверка"
    assert "уверенность" in copy.body
    assert copy.options[0].label == "Подтвердить"


def test_choice_fallback_title_und_cyrillic() -> None:
    assert HitlCopyPolicy.choice_fallback_title(locale="und", prose_hint="Привет, Геннадий!") == "Выберите один вариант"
    assert HitlCopyPolicy.choice_fallback_title(locale="en-US") == "Choose an option"


def test_tool_approval_russian() -> None:
    copy = HitlCopyPolicy.tool_approval(
        locale="ru",
        server_name="platform",
        tool_name="save_memory",
        side_effect="write",
        argument_preview="{}",
    )
    assert copy.title.startswith("Разрешить инструмент:")
    assert copy.options[0].label == "Разрешить вызов"
    assert copy.options[0].icon == "shield"


def test_tool_paused_russian() -> None:
    paused = HitlCopyPolicy.tool_paused(
        locale="ru-RU",
        server_name="platform",
        tool_name="save_memory",
        side_effect="write",
    )
    assert paused.title.startswith("Требуется")
    assert "Разрешить" in paused.body
