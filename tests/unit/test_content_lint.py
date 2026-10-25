"""Deterministic ContentDocument lint: valid schema, wrong answer for the user."""

from __future__ import annotations

from palatium_ai.domain.content import (
    CalloutBlock,
    CodeBlock,
    ContentBlock,
    ContentDocument,
    DocumentMeta,
    HeadingBlock,
    ListBlock,
    ListItem,
    ParagraphBlock,
    TableBlock,
)
from palatium_ai.domain.content.lint import ContentLint


def _doc(*blocks: ContentBlock, source_refs: tuple[str, ...] = ()) -> ContentDocument:
    return ContentDocument(
        locale="ru-RU",
        blocks=blocks,
        meta=DocumentMeta(confidence=0.9, source_refs=source_refs),
    )


def test_clean_document_has_no_findings() -> None:
    document = _doc(
        HeadingBlock(text="Итоги"),
        ParagraphBlock(text="Встреча перенесена на 15:00."),
        ListBlock(items=(ListItem(text="Выслать протокол"),)),
    )

    assert ContentLint.run(document).findings == ()


def test_internal_field_name_is_an_error() -> None:
    document = _doc(ParagraphBlock(text="Поле attachment_context заполнено."))

    findings = ContentLint.run(document).findings

    assert [(f.rule_id, f.severity, f.block_index) for f in findings] == [
        ("internal_marker_leak", "error", 0),
    ]


def test_code_block_is_verbatim_and_not_linted() -> None:
    document = _doc(CodeBlock(language="python", content="task_kind = 'plan'"))

    assert ContentLint.run(document).findings == ()


def test_page_marker_is_an_internal_leak() -> None:
    document = _doc(ParagraphBlock(text="Фрагмент [[page 4]] договора."))

    findings = ContentLint.run(document).findings

    assert [f.rule_id for f in findings] == ["internal_marker_leak"]


def test_citation_marker_within_source_count_is_fine() -> None:
    document = _doc(ParagraphBlock(text="Срок — 10 дней [1]."), source_refs=("dogovor.pdf",))

    assert ContentLint.run(document).findings == ()


def test_citation_marker_beyond_sources_is_dangling() -> None:
    document = _doc(ParagraphBlock(text="Срок — 10 дней [2]."), source_refs=("dogovor.pdf",))

    findings = ContentLint.run(document).findings

    assert [(f.rule_id, f.block_index) for f in findings] == [("dangling_citation", 0)]


def test_citation_marker_without_any_sources_is_dangling() -> None:
    document = _doc(ParagraphBlock(text="Смотри [1]."))

    findings = ContentLint.run(document).findings

    assert [f.rule_id for f in findings] == ["dangling_citation"]


def test_adjacent_duplicate_paragraph_is_reported_once() -> None:
    document = _doc(
        ParagraphBlock(text="Встреча перенесена на 15:00."),
        ParagraphBlock(text="  встреча   перенесена на 15:00.  "),
    )

    findings = ContentLint.run(document).findings

    assert [(f.rule_id, f.severity, f.block_index) for f in findings] == [
        ("duplicate_prose", "warning", 1),
    ]


def test_non_adjacent_duplicate_is_not_reported() -> None:
    document = _doc(
        ParagraphBlock(text="Один и тот же текст."),
        HeadingBlock(text="Раздел"),
        ParagraphBlock(text="Один и тот же текст."),
    )

    findings = ContentLint.run(document).findings

    assert [f.rule_id for f in findings] == []


def test_markdown_heading_inside_paragraph_is_residue() -> None:
    document = _doc(ParagraphBlock(text="## Итоги"))

    findings = ContentLint.run(document).findings

    assert [(f.rule_id, f.severity) for f in findings] == [("markdown_residue", "error")]


def test_table_cell_enumeration_is_not_markdown_residue() -> None:
    document = _doc(TableBlock(columns=("№", "Пункт"), rows=(("1", "1. Введение"),)))

    assert ContentLint.run(document).findings == ()


def test_heading_without_body_is_empty_section() -> None:
    document = _doc(HeadingBlock(text="Итоги"), HeadingBlock(text="Рекомендации"))

    findings = ContentLint.run(document).findings

    assert [(f.rule_id, f.block_index) for f in findings] == [
        ("empty_section", 0),
        ("empty_section", 1),
    ]


def test_heading_followed_by_callout_has_body() -> None:
    document = _doc(
        HeadingBlock(text="Итоги"),
        CalloutBlock(tone="info", body="Встреча перенесена."),
    )

    assert ContentLint.run(document).findings == ()


def test_report_counts_errors_separately_from_warnings() -> None:
    document = _doc(
        ParagraphBlock(text="## Итоги"),
        ParagraphBlock(text="## Итоги"),
    )

    report = ContentLint.run(document)

    assert report.error_count == 2
    assert len(report.findings) == 3  # residue ×2 + duplicate prose
