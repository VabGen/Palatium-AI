"""Stream paint prep — preview block matches final promote (layout_shift == 0)."""

from __future__ import annotations

from unittest.mock import patch

from palatium_ai.application.agents.formatter.answer_delta import emit_document_block
from palatium_ai.application.agents.formatter.stream_paint import prepare_block_for_stream_paint
from palatium_ai.application.services.turn_sse_bridge import TurnSseBridge
from palatium_ai.domain.content.content_document import (
    ContentDocument,
    DocumentMeta,
    KeyValueBlock,
    KeyValueItem,
    ListBlock,
    ListItem,
)
from palatium_ai.domain.policies.presentation_icons import PresentationIconPolicy


def test_prepare_promotes_label_list_to_kv() -> None:
    block = ListBlock(
        style="unordered",
        items=(
            ListItem(text="нет критериев", emphasis="Субъективность"),
            ListItem(text="нужна коррекция", emphasis="Индивидуальный подход"),
        ),
    )
    painted = prepare_block_for_stream_paint(block)
    assert painted.type == "kv"
    assert painted.items[0].label == "Субъективность"  # type: ignore[union-attr]
    assert painted.items[0].value == "нет критериев"  # type: ignore[union-attr]


def test_prepare_strips_row_icons_like_final_enrich() -> None:
    """LLM search icons on passport rows must not survive into block_delta."""
    block = KeyValueBlock(
        items=(
            KeyValueItem(label="Суд", value="Московский районный суд г. Гомеля", icon="search"),
            KeyValueItem(label="Дело №", value="123-4/2026", icon="search"),
        )
    )
    painted = prepare_block_for_stream_paint(block)
    assert painted.type == "kv"
    assert painted.items[0].icon is None  # type: ignore[union-attr]
    assert painted.items[1].icon is None  # type: ignore[union-attr]
    enriched = PresentationIconPolicy.enrich(
        ContentDocument(
            locale="ru-RU",
            blocks=(block,),
            meta=DocumentMeta(confidence=0.9, kind="letter"),
        )
    )
    assert enriched.blocks[0].items[0].icon is None  # type: ignore[union-attr]


def test_prepare_normalizes_legacy_nest_prefix() -> None:
    block = ListBlock(
        style="unordered",
        items=(
            ListItem(text="Корень"),
            ListItem(text="· Вложенный"),
        ),
    )
    painted = prepare_block_for_stream_paint(block)
    assert painted.type == "list"
    assert painted.items[1].text == "Вложенный"  # type: ignore[union-attr]
    assert painted.items[1].level == 1  # type: ignore[union-attr]


def test_prepare_keeps_nested_label_list_as_list() -> None:
    block = ListBlock(
        style="unordered",
        items=(
            ListItem(text="Субъективность заключений", emphasis="Субъективность заключений"),
            ListItem(
                text="Нет чётких критериев",
                emphasis="Субъективность заключений",
                level=1,
            ),
        ),
    )
    painted = prepare_block_for_stream_paint(block)
    assert painted.type == "list"


def test_emit_document_block_paints_promoted_kv() -> None:
    bridge = TurnSseBridge(stream_contract="structured_incremental")
    block = ListBlock(
        style="unordered",
        items=(
            ListItem(text="value a", emphasis="Label A"),
            ListItem(text="value b", emphasis="Label B"),
        ),
    )
    with patch(
        "palatium_ai.application.agents.formatter.answer_delta.get_turn_sse_bridge",
        return_value=bridge,
    ):
        emit_document_block(index=0, block=block)
    event = bridge.queue.get_nowait()
    assert event["event"] == "block_delta"
    assert event["block"]["type"] == "kv"
    assert bridge.sse_first_block_recorded is True
