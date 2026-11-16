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


def test_inventories_use_list_markers_for_analysis_not_plan() -> None:
    assert MechanicalRestructurePolicy.inventories_use_list_markers(shape="document_analysis", kind="analysis") is True
    assert MechanicalRestructurePolicy.inventories_use_list_markers(shape="auto", kind="analysis") is True
    assert MechanicalRestructurePolicy.inventories_use_list_markers(shape="plan", kind="guide") is False
    assert MechanicalRestructurePolicy.inventories_use_list_markers(shape="auto", kind="guide") is False


def test_demote_statusless_steps_to_unordered_catalogue() -> None:
    blocks = (
        HeadingBlock(level=2, text="Состав", icon="folder"),
        StepsBlock(
            items=(
                StepItem(title="Платформа", body="Сервисы и шлюз."),
                StepItem(title="UI", body="Формы и таблицы."),
            )
        ),
    )
    demoted = MechanicalRestructurePolicy.demote_inventory_steps(blocks)
    assert demoted is not None
    assert demoted[1].type == "list"
    assert demoted[1].style == "unordered"  # type: ignore[union-attr]
    assert demoted[1].items[0].emphasis == "Платформа"  # type: ignore[union-attr]
    assert demoted[1].items[0].icon is None  # type: ignore[union-attr]


def test_demote_under_check_heading_keeps_plain_bullets() -> None:
    """Heading chrome is enough — no per-row checklist icons (Big Tech laconic)."""
    blocks = (
        HeadingBlock(level=2, text="Рекомендации", icon="check"),
        StepsBlock(
            items=(
                StepItem(title="Права", body="Разграничить ИС."),
                StepItem(title="OSS", body="Проверить лицензии."),
            )
        ),
    )
    demoted = MechanicalRestructurePolicy.demote_inventory_steps(blocks)
    assert demoted is not None
    assert demoted[1].items[0].icon is None  # type: ignore[union-attr]
    assert demoted[1].items[1].icon is None  # type: ignore[union-attr]


def test_demote_keeps_steps_with_progress_status() -> None:
    blocks = (
        StepsBlock(
            items=(
                StepItem(title="A", body="one", status="done"),
                StepItem(title="B", body="two", status="active"),
            )
        ),
    )
    assert MechanicalRestructurePolicy.demote_inventory_steps(blocks) is None


def test_promote_label_list_to_kv_for_document_analysis() -> None:
    prior = _doc(
        HeadingBlock(text="Паспорт"),
        ListBlock(
            style="unordered",
            items=(
                ListItem(text="Поставка СЭД", emphasis="Назначение"),
                ListItem(text="10 рабочих дней", emphasis="Срок"),
            ),
        ),
        HeadingBlock(text="Риски"),
        ListBlock(
            style="unordered",
            items=(
                ListItem(text="сжатый срок", emphasis="Риск"),
                ListItem(text="нужна ЭЦП", emphasis="Условие"),
            ),
        ),
    )
    decision = MechanicalRestructurePolicy.apply(prior, shape="document_analysis", transformation="restructure")
    assert decision.document is not None
    assert decision.reason == "promoted_to_document_analysis"
    types = [block.type for block in decision.document.blocks]
    assert types.count("kv") >= 1
    assert "heading" in types
