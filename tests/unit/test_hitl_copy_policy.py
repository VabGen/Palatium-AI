"""HitlCopyPolicy — locale-aware quality / MCP card chrome."""

from __future__ import annotations

from palatium_ai.domain.hitl.copy import HitlCopyPolicy


def test_review_copy_russian() -> None:
    copy = HitlCopyPolicy.review(locale="ru-RU", confidence=0.5)
    assert copy.title == "Требуется проверка"
    assert "Контроль качества" in copy.body
    assert "0.50" not in copy.body
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
    assert "Контроль качества" in copy.body
    assert copy.options[0].label == "Подтвердить"


def test_choice_fallback_title_und_cyrillic() -> None:
    assert HitlCopyPolicy.choice_fallback_title(locale="und", prose_hint="Привет, Геннадий!") == "Выберите один вариант"
    assert HitlCopyPolicy.choice_fallback_title(locale="en-US") == "Choose an option"


def test_tool_approval_save_memory_hides_wire_details() -> None:
    """Big Tech: consequence + quote; no platform.save_memory / side_effect / ns UUID."""
    preview = (
        "ns=user/user-d60a00fb-5d6e-46a6-90a0-6f69b2e57de6; "
        "key=user_name; type=fact; text=имя пользователя Геннадий"
    )
    copy = HitlCopyPolicy.tool_approval(
        locale="ru",
        server_name="platform",
        tool_name="save_memory",
        side_effect="write",
        argument_preview=preview,
    )
    assert copy.title == "Сохранить в память?"
    assert "platform.save_memory" not in copy.title
    assert "Побочный эффект" not in copy.body
    assert "side_effect" not in copy.body.lower()
    assert "ns=" not in copy.body
    assert "user-d60a00fb" not in copy.body
    assert "Геннадий" in copy.body
    assert copy.options[0].label == "Сохранить"
    assert copy.options[1].label == "Не сохранять"
    assert copy.options[0].icon == "shield"


def test_tool_approval_unknown_tool_is_generic() -> None:
    copy = HitlCopyPolicy.tool_approval(
        locale="en-US",
        server_name="edms",
        tool_name="archive_document",
        side_effect="write",
        argument_preview="document_id=DOC-1, path=/tmp/x",
    )
    assert copy.title == "Allow this action?"
    assert "archive_document" not in copy.title
    assert "document_id" not in copy.body
    assert copy.options[0].label == "Allow"


def test_tool_paused_save_memory_russian() -> None:
    paused = HitlCopyPolicy.tool_paused(
        locale="ru-RU",
        server_name="platform",
        tool_name="save_memory",
        side_effect="write",
    )
    assert paused.heading == "Сохранить в память?"
    assert "MCP" not in paused.body
    assert "побочный эффект" not in paused.body
