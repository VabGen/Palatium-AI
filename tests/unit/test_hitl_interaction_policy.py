"""HITL interaction policy: choices become cards, never text menus."""

from __future__ import annotations

from palatium_ai.domain.content import (
    ActionSpec,
    ContentDocument,
    DocumentMeta,
    HeadingBlock,
    ListBlock,
    ListItem,
    ParagraphBlock,
)
from palatium_ai.domain.hitl.interaction_policy import HitlInteractionPolicy


def _menu_doc(*, items: list[str], title: str = "Pick one") -> ContentDocument:
    return ContentDocument(
        schema_version=1,
        locale="en-US",
        title=title,
        blocks=(
            HeadingBlock(type="heading", level=2, text=title, icon=None),
            ListBlock(
                type="list",
                style="ordered",
                items=tuple(ListItem(text=item, icon=None, emphasis=None) for item in items),
            ),
        ),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=(), interaction="none"),
    )


def test_plan_promotes_menu_shaped_list_to_choice_actions() -> None:
    doc = _menu_doc(
        items=[
            "Content Analysis – key provisions",
            "Risk Analysis – legal risks",
            "Compliance Analysis – regulations",
        ]
    )
    plan = HitlInteractionPolicy.plan(doc, requires_review=False)
    assert len(plan.choice_actions) == 3
    assert plan.choice_actions[0].label.startswith("Content Analysis")
    assert plan.mint_quality_review is False


def test_plan_uses_explicit_actions_and_interaction() -> None:
    doc = ContentDocument(
        schema_version=1,
        locale="en-US",
        title="Confirm",
        blocks=(ParagraphBlock(type="paragraph", text="Proceed?"),),
        actions=(
            ActionSpec(action_id="yes", label="Yes", kind="confirm", style="primary"),
            ActionSpec(action_id="no", label="No", kind="dismiss", style="danger"),
        ),
        meta=DocumentMeta(
            confidence=0.8,
            requires_review=False,
            source_refs=(),
            interaction="choice",
        ),
    )
    plan = HitlInteractionPolicy.plan(doc, requires_review=True)
    assert len(plan.choice_actions) == 2
    assert plan.mint_quality_review is True


def test_informational_multi_block_doc_not_promoted() -> None:
    doc = ContentDocument(
        schema_version=1,
        locale="en-US",
        title="Guide",
        blocks=(
            ParagraphBlock(type="paragraph", text="How to choose"),
            ListBlock(
                type="list",
                style="unordered",
                items=(
                    ListItem(text="Define the goal", icon=None, emphasis=None),
                    ListItem(text="Match the type", icon=None, emphasis=None),
                ),
            ),
            ParagraphBlock(type="paragraph", text="Then clarify format."),
            ListBlock(
                type="list",
                style="unordered",
                items=(
                    ListItem(text="Summary", icon=None, emphasis=None),
                    ListItem(text="Table", icon=None, emphasis=None),
                ),
            ),
        ),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=()),
    )
    plan = HitlInteractionPolicy.plan(doc, requires_review=False)
    assert plan.choice_actions == ()


def test_document_with_choice_framing_drops_menu_list() -> None:
    doc = _menu_doc(items=["A", "B", "C"], title="Types")
    plan = HitlInteractionPolicy.plan(doc, requires_review=False)
    framed = HitlInteractionPolicy.document_with_choice_framing(doc, choice_count=len(plan.choice_actions))
    assert all(block.type != "list" for block in framed.blocks)
    assert framed.meta.interaction == "choice"
    assert framed.actions == ()
    assert any(block.type in {"heading", "paragraph"} for block in framed.blocks)


def test_choice_interaction_without_mintable_actions_is_invalid() -> None:
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
    plan = HitlInteractionPolicy.plan(doc, requires_review=True)
    assert plan.reason == "formatter_output_invalid"
    assert plan.choice_actions == ()
    assert plan.mint_quality_review is False


def test_clarification_menu_too_small_fails_closed() -> None:
    # interaction=choice demands cards; a single action is not a choice set → fail-closed.
    doc = ContentDocument(
        schema_version=1,
        locale="en-US",
        title="Pick",
        blocks=(ParagraphBlock(type="paragraph", text="One path only"),),
        actions=(ActionSpec(action_id="only", label="Only option", kind="custom", style="primary"),),
        meta=DocumentMeta(
            confidence=0.9,
            requires_review=False,
            source_refs=(),
            interaction="choice",
        ),
    )
    plan = HitlInteractionPolicy.plan(
        doc,
        requires_review=False,
        task_kind="clarification_needed",
        selected_strategy="clarify",
    )
    assert plan.reason == "formatter_output_invalid"
    assert plan.choice_actions == ()
