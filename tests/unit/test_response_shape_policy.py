"""ShapeRecipePolicy — form of the answer body as a pure domain check."""

from __future__ import annotations

from palatium_ai.domain.content import ContentBlock, ContentDocument
from palatium_ai.domain.content.content_document import (
    DocumentMeta,
    HeadingBlock,
    ListBlock,
    ListItem,
    ParagraphBlock,
    StepItem,
    StepsBlock,
    TableBlock,
)
from palatium_ai.domain.policies.shape import ShapeRecipePolicy


def _doc(*blocks: ContentBlock) -> ContentDocument:
    return ContentDocument(
        locale="ru-RU",
        blocks=blocks,
        meta=DocumentMeta(confidence=0.9),
    )


def _table(columns: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> TableBlock:
    return TableBlock(columns=columns, rows=rows)


def test_coerce_unknown_labels_fall_back_to_auto() -> None:
    assert ShapeRecipePolicy.coerce(None) == "auto"
    assert ShapeRecipePolicy.coerce("bogus") == "auto"
    assert ShapeRecipePolicy.coerce("comparison_table") == "comparison_table"
    assert ShapeRecipePolicy.coerce(" plan ") == "plan"


def test_resolve_auto_has_no_recipe() -> None:
    assert ShapeRecipePolicy.resolve(shape="auto", task_kind="knowledge_request") is None


def test_resolve_skips_bodyless_turns() -> None:
    assert ShapeRecipePolicy.resolve(shape="plan", task_kind="social_conversation") is None
    assert ShapeRecipePolicy.resolve(shape="prose", task_kind="clarification_needed") is None


def test_resolve_returns_recipe_for_answer_turns() -> None:
    recipe = ShapeRecipePolicy.resolve(shape="plan", task_kind="knowledge_request")
    assert recipe is not None
    assert recipe.shape == "plan"
    assert recipe.block_requirements == ("steps", "list")


def test_comparison_table_accepts_wide_table() -> None:
    recipe = ShapeRecipePolicy.resolve(shape="comparison_table", task_kind="knowledge_request")
    assert recipe is not None
    document = _doc(
        _table(
            ("Параметр", "Скан_1", "Скан_2"),
            (("Формат", "PDF", "DOCX"), ("Подпись", "есть", "нет")),
        )
    )
    verdict = ShapeRecipePolicy.validate(document, recipe)
    assert verdict.satisfied is True
    assert verdict.reason == "ok"


def test_comparison_table_rejects_prose_only_document() -> None:
    recipe = ShapeRecipePolicy.resolve(shape="comparison_table", task_kind="knowledge_request")
    assert recipe is not None
    verdict = ShapeRecipePolicy.validate(_doc(ParagraphBlock(text="Похожи, но есть отличия.")), recipe)
    assert verdict.satisfied is False
    assert verdict.reason == "table_block_missing"


def test_comparison_table_rejects_single_column() -> None:
    recipe = ShapeRecipePolicy.resolve(shape="comparison_table", task_kind="knowledge_request")
    assert recipe is not None
    verdict = ShapeRecipePolicy.validate(
        _doc(_table(("Параметр",), (("Формат",), ("Подпись",)))),
        recipe,
    )
    assert verdict.satisfied is False
    assert verdict.reason == "table_too_narrow"


def test_comparison_table_rejects_one_compared_object() -> None:
    recipe = ShapeRecipePolicy.resolve(shape="comparison_table", task_kind="knowledge_request")
    assert recipe is not None
    # Attribute column + one object: every row still describes a single side.
    verdict = ShapeRecipePolicy.validate(
        _doc(_table(("Параметр", "Скан_1"), (("Формат", "PDF"), ("Подпись", "есть")))),
        recipe,
    )
    assert verdict.satisfied is False
    assert verdict.reason == "table_too_narrow"


def test_comparison_table_rejects_single_row() -> None:
    recipe = ShapeRecipePolicy.resolve(shape="comparison_table", task_kind="knowledge_request")
    assert recipe is not None
    verdict = ShapeRecipePolicy.validate(
        _doc(_table(("Параметр", "Скан_1", "Скан_2"), (("Формат", "PDF", "DOCX"),))),
        recipe,
    )
    assert verdict.satisfied is False
    assert verdict.reason == "table_too_short"


def test_document_analysis_requires_heading_and_paragraph() -> None:
    recipe = ShapeRecipePolicy.resolve(shape="document_analysis", task_kind="knowledge_request")
    assert recipe is not None
    satisfied = ShapeRecipePolicy.validate(
        _doc(HeadingBlock(text="Условия"), ParagraphBlock(text="Срок — 30 дней.")),
        recipe,
    )
    assert satisfied.satisfied is True

    no_paragraph = ShapeRecipePolicy.validate(_doc(HeadingBlock(text="Условия")), recipe)
    assert no_paragraph.reason == "paragraph_block_missing"

    no_heading = ShapeRecipePolicy.validate(_doc(ParagraphBlock(text="Срок — 30 дней.")), recipe)
    assert no_heading.reason == "heading_block_missing"


def test_plan_accepts_steps_and_ordered_list() -> None:
    recipe = ShapeRecipePolicy.resolve(shape="plan", task_kind="knowledge_request")
    assert recipe is not None
    steps = StepsBlock(
        items=(
            StepItem(title="Согласовать", body="Юрист подтверждает условия."),
            StepItem(title="Подписать", body="Стороны подписывают договор."),
        )
    )
    assert ShapeRecipePolicy.validate(_doc(steps), recipe).satisfied is True

    ordered = ListBlock(
        style="ordered",
        items=(ListItem(text="Согласовать"), ListItem(text="Подписать")),
    )
    assert ShapeRecipePolicy.validate(_doc(ordered), recipe).satisfied is True


def test_plan_rejects_unordered_list_and_short_steps() -> None:
    recipe = ShapeRecipePolicy.resolve(shape="plan", task_kind="knowledge_request")
    assert recipe is not None
    unordered = ListBlock(style="unordered", items=(ListItem(text="Согласовать"),))
    assert ShapeRecipePolicy.validate(_doc(unordered), recipe).reason == "plan_not_ordered"

    one_step = StepsBlock(items=(StepItem(title="Согласовать", body="Один шаг."),))
    assert ShapeRecipePolicy.validate(_doc(one_step), recipe).reason == "plan_too_short"


def test_prose_requires_paragraph() -> None:
    recipe = ShapeRecipePolicy.resolve(shape="prose", task_kind="knowledge_request")
    assert recipe is not None
    assert ShapeRecipePolicy.validate(_doc(ParagraphBlock(text="Объяснение.")), recipe).satisfied is True
    assert ShapeRecipePolicy.validate(_doc(HeadingBlock(text="Заголовок")), recipe).reason == "paragraph_block_missing"
