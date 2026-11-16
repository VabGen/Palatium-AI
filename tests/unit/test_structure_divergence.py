"""Structure divergence metric (Pre-P1 gate, single-writer turns)."""

from __future__ import annotations

from palatium_ai.domain.content import (
    CalloutBlock,
    ContentBlock,
    ContentDocument,
    DocumentMeta,
    HeadingBlock,
    ListBlock,
    ListItem,
    ParagraphBlock,
)
from palatium_ai.domain.policies.structure_divergence import measure_structure_divergence

_WORKER = (
    "Сравнение версий показало три отличия. В новой редакции добавлен раздел "
    "про оплату, изменён срок поставки и удалён пункт про гарантию."
)


def _document(*blocks: ContentBlock) -> ContentDocument:
    return ContentDocument(
        locale="ru-RU",
        title=None,
        blocks=blocks,
        meta=DocumentMeta(confidence=0.9),
    )


def test_verbatim_render_has_no_divergence() -> None:
    document = _document(
        ParagraphBlock(
            text=(
                "Сравнение версий показало три отличия. В новой редакции добавлен раздел "
                "про оплату, изменён срок поставки и удалён пункт про гарантию."
            )
        )
    )

    result = measure_structure_divergence(_WORKER, document)

    assert result.structure_divergence == 0.0
    assert result.block_coverage == 1.0
    assert result.uncovered_blocks == 0


def test_markup_is_normalized_away() -> None:
    """Markdown markers must not count as new content."""
    document = _document(
        HeadingBlock(text="Сравнение версий"),
        ListBlock(
            items=(
                ListItem(text="**Оплата**: добавлен раздел про оплату"),
                ListItem(text="Срок поставки изменён"),
            )
        ),
    )

    result = measure_structure_divergence(
        "## Сравнение версий\n- **Оплата**: добавлен раздел про оплату\n- Срок поставки изменён.",
        document,
    )

    assert result.structure_divergence == 0.0
    assert result.block_coverage == 1.0


def test_paraphrase_lowers_containment() -> None:
    document = _document(
        ParagraphBlock(
            text=(
                "Документы различаются по трём позициям: появился блок об оплате, "
                "пересмотрен график поставки, убрано упоминание гарантийных обязательств."
            )
        )
    )

    result = measure_structure_divergence(_WORKER, document)

    assert result.structure_divergence > 0.5
    assert result.block_coverage == 0.0


def test_added_blocks_lower_coverage_only() -> None:
    document = _document(
        ParagraphBlock(
            text=(
                "Сравнение версий показало три отличия. В новой редакции добавлен раздел "
                "про оплату, изменён срок поставки и удалён пункт про гарантию."
            )
        ),
        ParagraphBlock(
            text=(
                "Дополнительно рекомендуется согласовать изменения с юридическим отделом "
                "и зафиксировать новую редакцию в реестре договоров."
            )
        ),
    )

    result = measure_structure_divergence(_WORKER, document)

    assert result.block_coverage == 0.5
    assert result.uncovered_blocks == 1
    # Half the final shingles are new content, so divergence follows coverage down.
    assert 0.2 < result.structure_divergence < 0.8


def test_callout_title_counts_as_content() -> None:
    document = _document(CalloutBlock(tone="warning", title="Внимание", body="Срок поставки изменён."))

    covered = measure_structure_divergence("Внимание. Срок поставки изменён.", document)
    missed = measure_structure_divergence("Срок поставки изменён.", document)

    assert covered.block_coverage == 1.0
    assert missed.block_coverage == 0.0
    assert missed.structure_divergence > covered.structure_divergence


def test_empty_document_is_not_a_failure_signal() -> None:
    result = measure_structure_divergence(_WORKER, _document())

    assert result.structure_divergence == 0.0
    assert result.block_coverage == 1.0
    assert result.final_blocks == 0
