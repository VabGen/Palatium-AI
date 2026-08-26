"""InteractionAssembler + structural force-mint for exclusive menus."""

from __future__ import annotations

from palatium_ai.application.services.interaction_assembler import (
    InteractionAssembler,
    interaction_plan_log_fields,
)
from palatium_ai.domain.content import (
    ContentDocument,
    DocumentMeta,
    HeadingBlock,
    ListBlock,
    ListItem,
    ParagraphBlock,
)
from palatium_ai.domain.hitl.interaction_policy import HitlInteractionPolicy


def _topic_menu_doc(*, items: list[str]) -> ContentDocument:
    return ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title="Варианты тем",
        blocks=(
            ParagraphBlock(
                type="paragraph",
                text="Ниже приведены варианты тем, которые можно использовать для создания анекдота:",
            ),
            ListBlock(
                type="list",
                style="unordered",
                items=tuple(ListItem(text=item, icon=None, emphasis=None) for item in items),
            ),
        ),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=(), interaction="none"),
    )


_JOKE_TOPICS = [
    "Офисные будни и бюрократия",
    "Путешествия и туризм",
    "IT и программирование",
    "Семья и родственники",
    "Учёба и студенческая жизнь",
    "Спорт и фитнес",
    "Еда и рестораны",
    "Гаджеты и соцсети",
    "Медицина и поликлиники",
    "Погода и ЖКХ",
]


def test_structural_force_mints_menu_without_intent_flag() -> None:
    """S3: exclusive topic list must become cards even if Intent forgot requires_user_choice."""
    doc = _topic_menu_doc(items=_JOKE_TOPICS)
    plan = HitlInteractionPolicy.plan(
        doc,
        requires_review=False,
        task_kind="knowledge_request",
        selected_strategy="retrieve",
        requires_user_choice=False,
    )
    assert plan.menu_shaped is True
    assert plan.force_structural is True
    assert plan.required_choice is True
    assert plan.promoted_from == "list"
    assert len(plan.choice_actions) == 10
    assert plan.choice_actions[0].label.startswith("Офисные")


def test_assembler_strips_list_and_keeps_framing() -> None:
    doc = _topic_menu_doc(items=_JOKE_TOPICS)
    assembled = InteractionAssembler.assemble(
        doc,
        requires_review=False,
        task_kind="knowledge_request",
        requires_user_choice=False,
    )
    assert assembled.invalid is False
    assert assembled.strip_exclusive_menu is True
    assert assembled.document is not None
    assert all(block.type != "list" for block in assembled.document.blocks)
    assert assembled.document.meta.interaction == "choice"
    assert assembled.document.actions == ()
    assert len(assembled.plan.choice_actions) == 10
    fields = interaction_plan_log_fields(assembled)
    assert fields["force_structural"] is True
    assert fields["promoted_from"] == "list"


def test_assembler_fail_closed_when_choice_required_without_options() -> None:
    doc = ContentDocument(
        schema_version=1,
        locale="en-US",
        title="Pick",
        blocks=(ParagraphBlock(type="paragraph", text="Choose somehow"),),
        actions=(),
        meta=DocumentMeta(
            confidence=0.9,
            requires_review=False,
            source_refs=(),
            interaction="choice",
        ),
    )
    assembled = InteractionAssembler.assemble(doc, requires_review=False, requires_user_choice=True)
    assert assembled.invalid is True
    assert assembled.plan.reason == "formatter_output_invalid"


def test_heading_plus_list_still_menu_shaped() -> None:
    doc = ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title="Темы",
        blocks=(
            HeadingBlock(type="heading", level=2, text="Темы", icon=None),
            ListBlock(
                type="list",
                style="ordered",
                items=tuple(
                    ListItem(text=item, icon=None, emphasis=None)
                    for item in ("Путешествия", "Работа", "Семья", "Технологии")
                ),
            ),
        ),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=(), interaction="none"),
    )
    plan = HitlInteractionPolicy.plan(doc, requires_review=False, task_kind="knowledge_request")
    assert plan.menu_shaped is True
    assert len(plan.choice_actions) == 4
