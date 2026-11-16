"""response_shape=inventory — W10 p1_list catalogue as ListBlock (055)."""

from __future__ import annotations

from palatium_ai.domain.content import (
    ContentDocument,
    DocumentMeta,
    KeyValueBlock,
    ListBlock,
    ListItem,
    ParagraphBlock,
)
from palatium_ai.domain.content.content_document import KeyValueItem
from palatium_ai.domain.policies.mechanical_restructure import MechanicalRestructurePolicy
from palatium_ai.domain.policies.shape import ShapeRecipePolicy


def test_inventory_recipe_requires_list() -> None:
    recipe = ShapeRecipePolicy.resolve(shape="inventory", task_kind="knowledge_request")
    assert recipe is not None
    assert recipe.block_requirements == ("list",)


def test_promote_parallel_paragraphs_to_list() -> None:
    blocks = (
        ParagraphBlock(type="paragraph", text="Производительность OLTP."),
        ParagraphBlock(type="paragraph", text="ACID и целостность."),
        ParagraphBlock(type="paragraph", text="Расширяемость типов."),
    )
    promoted = MechanicalRestructurePolicy.promote_parallel_paragraphs_to_list(blocks)
    assert promoted is not None
    assert len(promoted) == 1
    assert isinstance(promoted[0], ListBlock)
    assert promoted[0].style == "unordered"
    assert len(promoted[0].items) == 3


def test_promote_kv_panel_to_inventory_list() -> None:
    blocks = (
        KeyValueBlock(
            type="kv",
            items=(
                KeyValueItem(label="Производительность", value="MVCC и параллельные запросы"),
                KeyValueItem(label="Надёжность", value="ACID и WAL"),
                KeyValueItem(label="Расширяемость", value="типы и индексы"),
            ),
        ),
    )
    promoted = MechanicalRestructurePolicy.promote_parallel_paragraphs_to_list(blocks)
    assert promoted is not None
    assert len(promoted) == 1
    assert isinstance(promoted[0], ListBlock)
    assert len(promoted[0].items) == 3
    assert promoted[0].items[0].emphasis == "Производительность"


def test_inventory_list_is_not_hitl_menu() -> None:
    """response_shape=inventory: catalogue ListBlock stays the answer (W10 p1_list)."""
    from palatium_ai.application.services.interaction_assembler import InteractionAssembler
    from palatium_ai.domain.hitl.interaction_policy import HitlInteractionPolicy

    doc = ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title="Преимущества PostgreSQL",
        blocks=(
            ListBlock(
                type="list",
                style="unordered",
                items=(
                    ListItem(text="MVCC и параллельные транзакции", emphasis="Производительность"),
                    ListItem(text="ACID и WAL", emphasis="Надёжность"),
                    ListItem(text="Расширяемые типы", emphasis="Гибкость"),
                ),
            ),
        ),
        actions=(),
        meta=DocumentMeta(
            confidence=0.9,
            requires_review=False,
            source_refs=(),
            interaction="choice",
            kind="analysis",
        ),
    )
    plan = HitlInteractionPolicy.plan(
        doc,
        requires_review=False,
        task_kind="knowledge_request",
        response_shape="inventory",
    )
    assert plan.reason == "catalogue_answer"
    assert plan.choice_actions == ()
    assert plan.required_choice is False

    assembled = InteractionAssembler.assemble(
        doc,
        requires_review=False,
        task_kind="knowledge_request",
        response_shape="inventory",
    )
    assert assembled.strip_exclusive_menu is False
    assert assembled.document is not None
    assert assembled.document.meta.interaction == "none"
    assert any(block.type == "list" for block in assembled.document.blocks)
    assert assembled.plan.reason == "catalogue_answer"


def test_inventory_shape_validates_list_document() -> None:
    doc = ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title=None,
        blocks=(
            ListBlock(
                type="list",
                style="unordered",
                items=(
                    ListItem(text="A"),
                    ListItem(text="B"),
                    ListItem(text="C"),
                ),
            ),
        ),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=()),
    )
    recipe = ShapeRecipePolicy.resolve(shape="inventory", task_kind="knowledge_request")
    assert recipe is not None
    verdict = ShapeRecipePolicy.validate(doc, recipe)
    assert verdict.satisfied is True
