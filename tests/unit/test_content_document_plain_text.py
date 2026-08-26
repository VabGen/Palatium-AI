"""ContentDocument.plain_text must keep body blocks for dialog transcript."""

from __future__ import annotations

from datetime import UTC, datetime

from palatium_ai.application.services.intent_service import (
    _assistant_turn_content,
    _assistant_turn_payload,
)
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.content import (
    ContentDocument,
    DocumentMeta,
    ListBlock,
    ListItem,
    ParagraphBlock,
)
from palatium_ai.domain.hitl.cards import HITLCardView, HITLOption


def test_plain_text_includes_list_body_not_only_title() -> None:
    doc = ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title="План встречи",
        blocks=(
            ListBlock(
                style="unordered",
                items=(
                    ListItem(text="Завершение встречи (15:00–15:15) — итоги"),
                    ListItem(text="Отправка протокола"),
                ),
            ),
        ),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False),
    )
    text = doc.plain_text()
    assert "План встречи" in text
    assert "15:00" in text
    assert doc.preview_text() == "План встречи"


def test_assistant_turn_content_uses_plain_text() -> None:
    doc = ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title="План встречи",
        blocks=(ParagraphBlock(text="Завершение в 15:15"),),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False),
    )
    result = FormatterTaskResult(
        task_id="t1",
        agent_role="formatter",
        status="success",
        confidence=0.9,
        requires_review=False,
        output=doc,
    )
    content = _assistant_turn_content(result)
    assert "15:15" in content
    assert content != "План встречи"


def test_assistant_turn_payload_includes_hitl_cards() -> None:
    doc = ContentDocument(
        schema_version=1,
        locale="en-US",
        title="Pick analysis",
        blocks=(ParagraphBlock(text="Choose one"),),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False),
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    card = HITLCardView(
        card_id="card-1",
        thread_id="thread-1",
        task_id="task-1",
        purpose="user_choice",
        title="Options",
        options=(
            HITLOption(
                action_id="opt_a",
                label="Legal review",
                kind="custom",
                style="primary",
                action_token="tok-a",
            ),
        ),
        risk_score=0.2,
        status="pending",
        created_at=now,
        expires_at=now,
    )
    result = FormatterTaskResult(
        task_id="t1",
        agent_role="formatter",
        status="partial",
        confidence=0.9,
        requires_review=False,
        output=doc,
        hitl_cards=(card,),
    )
    payload = _assistant_turn_payload(result)
    assert payload is not None
    assert payload["schema"] == "assistant_turn_v1"
    assert isinstance(payload["document"], dict)
    cards = payload["hitl_cards"]
    assert isinstance(cards, list)
    assert len(cards) == 1
    assert cards[0]["card_id"] == "card-1"
    assert cards[0]["purpose"] == "user_choice"
    options = cards[0]["options"]
    assert isinstance(options, list) and options
    assert options[0]["action_token"] == ""
    assert options[0]["action_id"] == "opt_a"
