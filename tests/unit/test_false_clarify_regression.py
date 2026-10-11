"""Regression: «расскажи анекдот на тему» after an upload became a HITL choice menu.

Class of bug: a complete creative/answer ask, labelled ``clarification_needed`` by the
history-blind Intent, was turned into choice cards built from the previous task.
Covered contracts: ClarificationGatePolicy, Contextualizer ``slot_filled_by_prior``,
ContinuityPolicy, DiscreteChoiceSynthesisPolicy.fresh_prior, HitlInteractionPolicy.
"""

from __future__ import annotations

import json

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from palatium_ai.application.agents.context_enricher.continuation.parsing import parse_contextualizer_output
from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.content import ActionSpec, ContentDocument, DocumentMeta, ParagraphBlock
from palatium_ai.domain.hitl.interaction_policy import HitlInteractionPolicy
from palatium_ai.domain.hitl.option_synthesis import DiscreteChoiceSynthesisPolicy
from palatium_ai.domain.memory.contextualizer import ContextualizerOutput
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.domain.policies import CLARIFY_MIN_CONFIDENCE, ClarificationGatePolicy, ContinuityPolicy

_DOC_ANSWER = "Документ — договор на охрану массового мероприятия: обязанности сторон, сроки, ответственность."


def _turn(role: str, content: str, seq: int) -> DialogTurn:
    return DialogTurn(
        id=uuid4(),
        thread_id="t1",
        role=role,  # type: ignore[arg-type]  # Literal role; test passes valid values
        content=content,
        seq=seq,
        created_at=datetime.now(UTC),
    )


def _dialog(*contents: tuple[str, str]) -> DialogTurnWindow:
    return DialogTurnWindow(
        thread_id="t1",
        turns=tuple(_turn(role, text, i) for i, (role, text) in enumerate(contents)),
        limit=12,
    )


def _intent(**overrides: object) -> IntentClassifierOutput:
    base: dict[str, object] = {
        "task_kind": "clarification_needed",
        "requires_mcp": False,
        "candidate_capabilities": (),
        "confidence": 0.9,
        "reasoning": "history-blind",
    }
    base.update(overrides)
    return IntentClassifierOutput(**base)  # type: ignore[arg-type]  # test factory


# --- ClarificationGatePolicy -------------------------------------------------


def test_gate_demotes_clarify_that_names_no_gap() -> None:
    gated = ClarificationGatePolicy.apply(_intent(underspecification_kind="none"))
    assert gated.task_kind == "knowledge_request"
    assert gated.requires_user_choice is False
    assert "clarification_gate" in gated.reasoning


def test_gate_demotes_low_confidence_clarify_even_with_gap() -> None:
    raw = _intent(
        underspecification_kind="discrete_choice",
        requires_user_choice=True,
        candidate_capabilities=("user_choice",),
        confidence=CLARIFY_MIN_CONFIDENCE - 0.05,
    )
    gated = ClarificationGatePolicy.apply(raw)
    assert gated.task_kind == "knowledge_request"
    assert gated.underspecification_kind == "none"
    assert "user_choice" not in gated.candidate_capabilities


@pytest.mark.parametrize("underspec", ("open_text", "discrete_choice"))
def test_gate_keeps_confident_clarify_with_named_gap(underspec: str) -> None:
    raw = _intent(underspecification_kind=underspec, confidence=CLARIFY_MIN_CONFIDENCE)
    assert ClarificationGatePolicy.apply(raw) == raw


def test_gate_ignores_non_clarify_kinds() -> None:
    raw = _intent(task_kind="knowledge_request", confidence=0.1)
    assert ClarificationGatePolicy.apply(raw) == raw


# --- Contextualizer slot_filled_by_prior ---------------------------------------


def _ctx_json(**fields: object) -> str:
    payload: dict[str, object] = {
        "rewritten_query": "Расскажи анекдот на тему охраны массового мероприятия",
        "continuation_kind": "answer",
        "refers_to_prior": True,
        "slot_filled_by_prior": True,
        "confidence": 0.85,
        "reasoning": "topic pointer resolved from prior",
    }
    payload.update(fields)
    return json.dumps(payload, ensure_ascii=False)


def test_slot_filled_requires_prior_bound_answer() -> None:
    assert parse_contextualizer_output(_ctx_json()).choice_slot_filled is True


@pytest.mark.parametrize(
    "fields",
    (
        {"refers_to_prior": False},
        {"continuation_kind": "new_topic"},
        {"continuation_kind": "clarify"},
        {"slot_filled_by_prior": False},
    ),
)
def test_slot_filled_rejected_without_prior_binding(fields: dict[str, object]) -> None:
    assert parse_contextualizer_output(_ctx_json(**fields)).choice_slot_filled is False


# --- ContinuityPolicy end-to-end on the symptom ---------------------------------


def test_joke_on_document_topic_answers_instead_of_choice_menu() -> None:
    dialog = _dialog(("user", "Что в файле ScanУВД.pdf?"), ("assistant", _DOC_ANSWER))
    ctx = ContextualizerOutput(
        rewritten_query="Расскажи анекдот на тему охраны массового мероприятия",
        continuation_kind="answer",
        confidence=0.85,
        refers_to_prior=True,
        prior_assistant_excerpt=_DOC_ANSWER,
        reasoning="topic from prior",
        choice_slot_filled=True,
    )
    raw = _intent(
        underspecification_kind="discrete_choice",
        requires_user_choice=True,
        candidate_capabilities=("user_choice",),
        confidence=0.8,
    )
    effective = ContinuityPolicy.resolve(contextualizer=ctx, dialog=dialog, raw_intent=raw)
    assert effective.task_kind == "knowledge_request"
    assert effective.requires_user_choice is False
    assert effective.underspecification_kind == "none"
    assert effective.suppress_intent_hitl is True


def test_low_confidence_contextualizer_clarify_does_not_stop_the_turn() -> None:
    dialog = _dialog(("user", "Что в файле?"), ("assistant", _DOC_ANSWER))
    ctx = ContextualizerOutput(
        rewritten_query="Расскажи анекдот",
        continuation_kind="clarify",
        confidence=CLARIFY_MIN_CONFIDENCE - 0.2,
        refers_to_prior=False,
        reasoning="unsure",
    )
    raw = _intent(task_kind="knowledge_request", candidate_capabilities=("compose",))
    effective = ContinuityPolicy.resolve(contextualizer=ctx, dialog=dialog, raw_intent=raw)
    assert effective.task_kind == "knowledge_request"
    assert effective.requires_user_choice is False


# --- HITL: stale prior + untagged actions ---------------------------------------


def test_fresh_prior_admits_latest_exchange_only() -> None:
    old_prior = "Варианты ответа на обращение гражданина по поводу ремонта дороги"
    dialog = _dialog(
        ("user", "Напиши ответ на обращение"),
        ("assistant", old_prior),
        ("user", "Что в файле?"),
        ("assistant", _DOC_ANSWER),
    )
    assert DiscreteChoiceSynthesisPolicy.fresh_prior(_DOC_ANSWER, dialog) == _DOC_ANSWER
    assert DiscreteChoiceSynthesisPolicy.fresh_prior(old_prior, dialog) is None
    assert DiscreteChoiceSynthesisPolicy.fresh_prior(_DOC_ANSWER, None) is None


def _doc_with_actions(interaction: str, n_actions: int) -> ContentDocument:
    return ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title=None,
        blocks=(ParagraphBlock(type="paragraph", text="Ответ готов."),),
        actions=tuple(
            ActionSpec(action_id=f"a{i}", label=f"Вариант {i}", kind="custom", style="secondary") for i in range(n_actions)
        ),
        meta=DocumentMeta(
            confidence=0.9,
            requires_review=False,
            source_refs=(),
            interaction=interaction,  # type: ignore[arg-type]  # closed Literal; valid values
        ),
    )


def test_untagged_formatter_actions_are_not_a_required_choice() -> None:
    plan = HitlInteractionPolicy.plan(_doc_with_actions("none", 2), requires_review=False)
    assert plan.choice_actions == ()


def test_tagged_choice_actions_still_become_cards() -> None:
    plan = HitlInteractionPolicy.plan(_doc_with_actions("choice", 2), requires_review=False)
    assert len(plan.choice_actions) == 2
