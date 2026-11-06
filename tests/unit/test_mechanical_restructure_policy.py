"""MechanicalRestructurePolicy — 0-LLM reshape of a prior ContentDocument."""

from __future__ import annotations

from palatium_ai.domain.content.content_document import (
    ContentDocument,
    DocumentMeta,
    HeadingBlock,
    ListBlock,
    ListItem,
    ParagraphBlock,
    StepItem,
    StepsBlock,
    TableBlock,
)
from palatium_ai.domain.policies.mechanical_restructure import MechanicalRestructurePolicy


def _doc(*blocks: object) -> ContentDocument:
    return ContentDocument(
        locale="ru-RU",
        blocks=blocks,  # type: ignore[arg-type]
        meta=DocumentMeta(confidence=0.9, kind="analysis"),
    )


def test_reuse_when_prior_already_matches_plan() -> None:
    prior = _doc(
        StepsBlock(
            items=(
                StepItem(title="A", body="one"),
                StepItem(title="B", body="two"),
            )
        )
    )
    decision = MechanicalRestructurePolicy.apply(prior, shape="plan", transformation="restructure")
    assert decision.document is prior
    assert decision.reason == "prior_already_satisfies_shape"


def test_promote_ordered_list_with_emphasis_to_steps() -> None:
    prior = _doc(
        ListBlock(
            style="ordered",
            items=(
                ListItem(text="собрать документы", emphasis="Подготовка"),
                ListItem(text="подать заявление", emphasis="Отправка"),
            ),
        )
    )
    decision = MechanicalRestructurePolicy.apply(prior, shape="plan", transformation="restructure")
    assert decision.document is not None
    assert decision.reason == "promoted_to_plan"
    assert decision.document.blocks[0].type == "steps"
    assert decision.document.blocks[0].items[0].title == "Подготовка"  # type: ignore[union-attr]


def test_flatten_to_prose() -> None:
    prior = _doc(
        HeadingBlock(text="Раздел"),
        ParagraphBlock(text="Текст."),
        ListBlock(items=(ListItem(text="пункт"),)),
    )
    decision = MechanicalRestructurePolicy.apply(prior, shape="prose", transformation="restructure")
    assert decision.document is not None
    assert all(block.type == "paragraph" for block in decision.document.blocks)


def test_comparison_without_table_needs_llm() -> None:
    prior = _doc(ParagraphBlock(text="Они отличаются по сроку."))
    decision = MechanicalRestructurePolicy.apply(prior, shape="comparison_table", transformation="restructure")
    assert decision.document is None
    assert decision.reason == "shape_needs_llm"


def test_expand_always_needs_llm() -> None:
    prior = _doc(
        TableBlock(
            columns=("П", "A", "B"),
            rows=(("Срок", "1", "2"), ("Оплата", "x", "y")),
        )
    )
    decision = MechanicalRestructurePolicy.apply(prior, shape="comparison_table", transformation="expand")
    assert decision.document is None
    assert decision.reason == "content_transform_needs_llm"


def test_auto_restructure_reuses_prior() -> None:
    prior = _doc(ParagraphBlock(text="Готовый ответ."))
    decision = MechanicalRestructurePolicy.apply(prior, shape="auto", transformation="restructure")
    assert decision.document is prior
    assert decision.reason == "restructure_reuse_prior"
