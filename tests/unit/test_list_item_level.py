"""ListItem.level — typed nesting for any list scenario."""

from __future__ import annotations

from palatium_ai.domain.content.content_document import (
    ContentDocument,
    DocumentMeta,
    ListBlock,
    ListItem,
    NESTED_ITEM_PREFIX,
    normalize_document_list_nesting,
    normalize_list_item_nesting,
)
from palatium_ai.domain.content.markdown_blocks import prose_to_blocks


def test_normalize_strips_legacy_prefix_into_level() -> None:
    text, level = normalize_list_item_nesting(f"{NESTED_ITEM_PREFIX}подпункт", 0)
    assert text == "подпункт"
    assert level == 1


def test_document_normalize_lifts_prefix() -> None:
    document = ContentDocument(
        locale="ru-RU",
        blocks=(
            ListBlock(
                items=(
                    ListItem(text="корень"),
                    ListItem(text=f"{NESTED_ITEM_PREFIX}вложенный"),
                )
            ),
        ),
        meta=DocumentMeta(confidence=0.9),
    )
    out = normalize_document_list_nesting(document)
    items = out.blocks[0].items  # type: ignore[union-attr]
    assert items[0].level == 0
    assert items[1].text == "вложенный"
    assert items[1].level == 1
    assert NESTED_ITEM_PREFIX not in items[1].text


def test_indented_bullet_sets_level() -> None:
    _title, blocks = prose_to_blocks("- корень\n  - вложенный\n")
    assert len(blocks) == 1
    assert isinstance(blocks[0], ListBlock)
    assert blocks[0].items[0].level == 0
    assert blocks[0].items[1].level == 1
    assert not blocks[0].items[1].text.startswith(NESTED_ITEM_PREFIX)
