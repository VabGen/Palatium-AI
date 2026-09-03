"""Discrete choice underspecification → synthesis policy + Intent normalize."""

from __future__ import annotations

from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.agents.user_choice_intent import UserChoiceIntentPolicy
from palatium_ai.domain.content import (
    ActionSpec,
    ContentDocument,
    DocumentMeta,
    ParagraphBlock,
)
from palatium_ai.domain.hitl.interaction_policy import HitlInteractionPolicy
from palatium_ai.domain.hitl.option_synthesis import DiscreteChoiceSynthesisPolicy
from palatium_ai.domain.policies import ContinuityPolicy


def test_discrete_choice_forces_requires_user_choice_and_clarify() -> None:
    raw = IntentClassifierOutput(
        task_kind="knowledge_request",
        requires_mcp=False,
        requires_user_choice=False,
        underspecification_kind="discrete_choice",
        candidate_capabilities=(),
        confidence=0.92,
        reasoning="action named but discrete slot missing",
    )
    out = UserChoiceIntentPolicy.normalize(raw)
    assert out.requires_user_choice is True
    assert out.underspecification_kind == "discrete_choice"
    assert out.task_kind == "clarification_needed"
    assert "user_choice" in out.candidate_capabilities


def test_open_text_does_not_force_choice_cards() -> None:
    raw = IntentClassifierOutput(
        task_kind="knowledge_request",
        requires_mcp=False,
        requires_user_choice=True,
        underspecification_kind="open_text",
        candidate_capabilities=("user_choice",),
        confidence=0.9,
        reasoning="need free-form document paste",
    )
    out = UserChoiceIntentPolicy.normalize(raw)
    assert out.requires_user_choice is False
    assert out.underspecification_kind == "open_text"
    assert out.task_kind == "clarification_needed"


def test_continuity_preserves_discrete_choice() -> None:
    raw = UserChoiceIntentPolicy.normalize(
        IntentClassifierOutput(
            task_kind="knowledge_request",
            requires_mcp=False,
            requires_user_choice=False,
            underspecification_kind="discrete_choice",
            candidate_capabilities=(),
            confidence=0.9,
            reasoning="incomplete discrete slot",
        )
    )
    effective = ContinuityPolicy.resolve(contextualizer=None, dialog=None, raw_intent=raw)
    assert effective.underspecification_kind == "discrete_choice"
    assert effective.requires_user_choice is True
    assert effective.task_kind == "clarification_needed"


def test_needs_synthesis_when_choice_required_without_options() -> None:
    doc = ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title="Уточнение",
        blocks=(ParagraphBlock(type="paragraph", text="На какую тему?"),),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=(), interaction="none"),
    )
    plan = HitlInteractionPolicy.plan(doc, requires_review=False, requires_user_choice=True)
    assert DiscreteChoiceSynthesisPolicy.needs_synthesis(
        requires_user_choice=True,
        underspecification_kind="discrete_choice",
        plan=plan,
    )


def test_merge_synthesized_actions_sets_choice_interaction() -> None:
    actions = (
        ActionSpec(action_id="choice_1", label="Путешествия", kind="custom", style="primary"),
        ActionSpec(action_id="choice_2", label="Работа", kind="custom", style="secondary"),
        ActionSpec(action_id="choice_3", label="Семья", kind="custom", style="secondary"),
    )
    doc = DiscreteChoiceSynthesisPolicy.merge_actions_into_document(
        None,
        actions,
        framing_text="Выберите тему анекдота:",
    )
    assert doc.meta.interaction == "choice"
    assert len(doc.actions) == 3
    plan = HitlInteractionPolicy.plan(doc, requires_review=False, requires_user_choice=True)
    assert len(plan.choice_actions) == 3
    assert plan.reason != "formatter_output_invalid"
