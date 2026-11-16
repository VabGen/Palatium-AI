"""Resolvable ``[n]`` stay in prose for UI cite chips; dangling markers untouched."""

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


def test_keeps_resolvable_marker_for_inline_chips() -> None:
    doc = _doc(ParagraphBlock(text="Вывод по документу[1]"))

    cleaned = strip_citation_markers(doc, source_count=len(doc.meta.source_refs))

    block = cleaned.blocks[0]
    assert isinstance(block, ParagraphBlock)
    assert "[1]" in block.text
    assert cleaned is doc


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


def test_list_and_table_keep_resolvable_markers() -> None:
    doc = _doc(
        ListBlock(style="unordered", items=(ListItem(text="Пункт[1]"),)),
        TableBlock(columns=("A",), rows=(("ячейка[1]",),)),
    )

    cleaned = strip_citation_markers(doc, source_count=1)

    assert cleaned is doc
    list_block = cleaned.blocks[0]
    assert isinstance(list_block, ListBlock)
    assert list_block.items[0].text == "Пункт[1]"


def test_no_sources_is_noop() -> None:
    doc = _doc(ParagraphBlock(text="Вывод[1]"), refs=())

    assert strip_citation_markers(doc, source_count=0) is doc
