"""``[n]`` markers in prose duplicate ``meta.source_refs`` — they must not reach the UI."""

from __future__ import annotations

from palatium_ai.domain.content import (
    CodeBlock,
    ContentDocument,
    DocumentMeta,
    ListBlock,
    ListItem,
    ParagraphBlock,
    TableBlock,
)
from palatium_ai.domain.content.citations.markers import strip_citation_markers


def _doc(*blocks: object, refs: tuple[str, ...] = ("Обращение.docx",)) -> ContentDocument:
    return ContentDocument(
        schema_version=1,
        locale="ru-RU",
        blocks=blocks,  # type: ignore[arg-type]
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=refs),
    )


def test_strips_marker_that_resolves_to_a_source() -> None:
    doc = _doc(ParagraphBlock(text="[1] Вывод по документу[1]"))

    cleaned = strip_citation_markers(doc, source_count=len(doc.meta.source_refs))

    block = cleaned.blocks[0]
    assert isinstance(block, ParagraphBlock)
    assert block.text == "Вывод по документу"


def test_keeps_marker_without_a_matching_source() -> None:
    """A dangling ``[3]`` is a broken promise: the lint rule reports it, not silence."""
    doc = _doc(ParagraphBlock(text="Вывод[3]"))

    cleaned = strip_citation_markers(doc, source_count=1)

    block = cleaned.blocks[0]
    assert isinstance(block, ParagraphBlock)
    assert block.text == "Вывод[3]"


def test_keeps_markdown_link_that_looks_like_a_marker() -> None:
    doc = _doc(ParagraphBlock(text="подробнее [1](https://example.com/a)"))

    cleaned = strip_citation_markers(doc, source_count=1)

    block = cleaned.blocks[0]
    assert isinstance(block, ParagraphBlock)
    assert block.text == "подробнее [1](https://example.com/a)"


def test_code_block_is_verbatim() -> None:
    doc = _doc(CodeBlock(language="python", content="items = data[1]"))

    cleaned = strip_citation_markers(doc, source_count=1)

    assert cleaned.blocks == doc.blocks


def test_drops_list_row_and_table_cell_content_is_cleaned() -> None:
    doc = _doc(
        ListBlock(style="unordered", items=(ListItem(text="[1]"), ListItem(text="Пункт[1]"))),
        TableBlock(columns=("A",), rows=(("[1] ячейка",),)),
    )

    cleaned = strip_citation_markers(doc, source_count=1)

    assert len(cleaned.blocks) == 2
    list_block = cleaned.blocks[0]
    assert isinstance(list_block, ListBlock)
    assert [item.text for item in list_block.items] == ["Пункт"]
    table = cleaned.blocks[1]
    assert isinstance(table, TableBlock)
    assert table.rows == (("ячейка",),)


def test_no_sources_means_nothing_to_strip() -> None:
    doc = _doc(ParagraphBlock(text="Вывод[1]"), refs=())

    assert strip_citation_markers(doc, source_count=0) is doc
