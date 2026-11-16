# tests/unit/test_uncertainty_disposition_conductivity.py

"""§4: disposition conducts Intent → ContextPacket → Formatter/Critic (contract field)."""

from __future__ import annotations

from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.critic import CriticInput
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.policies.critic import CriticPolicy
from palatium_ai.domain.policies.types import ResolvedUncertaintyDisposition
from palatium_ai.domain.policies.uncertainty import ASSUMPTION_MARK, UncertaintyPolicy, UncertaintySignals


def _fake_intent_with_disposition(
    disposition: ResolvedUncertaintyDisposition,
) -> IntentClassifierOutput:
    """Stand-in for Intent after UncertaintyPolicy.for_pipeline attach (not LLM)."""
    return IntentClassifierOutput(
        task_kind="knowledge_request",
        requires_mcp=False,
        confidence=0.9,
        reasoning="conductivity_fixture",
        uncertainty_disposition=disposition,
    )


def _packet_from_intent(intent: IntentClassifierOutput) -> ContextPacket:
    return ContextPacket(
        task_id="cond-1",
        user_text="incomplete ask",
        task_kind=intent.task_kind,
        route="researcher",
        route_plan="conductivity",
        requires_mcp=intent.requires_mcp,
        grounding=intent.grounding,
        execution_plan=ToolExecutionPlan(
            strategy="reason_only",
            requires_tool_call=False,
            rationale="conductivity",
        ),
        context_summary="conductivity",
        uncertainty_disposition=intent.uncertainty_disposition,
    )


def test_disposition_conducts_intent_to_formatter_and_critic() -> None:
    decision = UncertaintyPolicy.for_pipeline(
        UncertaintySignals(
            task_kind="knowledge_request",
            confidence=0.8,
            grounding="optional",
            retrieval_empty=True,
        )
    )
    assert decision.disposition == "default_with_mark"
    resolved = UncertaintyPolicy.resolved_disposition(decision)

    intent = _fake_intent_with_disposition(resolved)
    packet = _packet_from_intent(intent)
    assert packet.uncertainty_disposition == "default_with_mark"

    formatter = FormatterInput(
        task_id=packet.task_id,
        context_packet=packet,
        uncertainty_disposition=packet.uncertainty_disposition,
    )
    critic = CriticInput(
        task_id=packet.task_id,
        context_packet=packet,
        classification_confidence=intent.confidence,
        classification_reasoning=intent.reasoning,
        uncertainty_disposition=packet.uncertainty_disposition,
    )

    assert formatter.uncertainty_disposition == intent.uncertainty_disposition
    assert critic.uncertainty_disposition == intent.uncertainty_disposition
    assert UncertaintyPolicy.requires_assumption_mark(formatter.uncertainty_disposition)
    assert UncertaintyPolicy.mark_exempt_from_verbosity(
        disposition=formatter.uncertainty_disposition,
        verbosity_budget="minimal",
    )
    marked = f"{ASSUMPTION_MARK} degraded path"
    assert UncertaintyPolicy.assumption_mark_preserved(
        marked,
        disposition=formatter.uncertainty_disposition,
    )


def test_honest_refusal_disposition_is_critic_passthrough() -> None:
    """Justified refusal is policy success — Critic must not fail completeness."""
    intent = _fake_intent_with_disposition("honest_refusal")
    intent = intent.model_copy(update={"uncertainty_reason": "out_of_scope"})
    packet = _packet_from_intent(intent).model_copy(update={"uncertainty_reason": "out_of_scope"})
    critic_in = CriticInput(
        task_id=packet.task_id,
        context_packet=packet,
        classification_confidence=0.95,
        classification_reasoning="out_of_scope",
        worker_summary="Cannot help with that ask.",
        selected_strategy="reason_only",
        uncertainty_disposition=packet.uncertainty_disposition,
        uncertainty_reason=packet.uncertainty_reason,
    )
    gate = CriticPolicy.decide(
        selected_strategy=critic_in.selected_strategy,
        task_kind=packet.task_kind,
        continuation_kind=None,
        classification_confidence=critic_in.classification_confidence,
        confidence_threshold=0.7,
        requires_mcp=False,
        requires_tool_call=False,
        worker_summary=critic_in.worker_summary,
        uncertainty_disposition=critic_in.uncertainty_disposition,
        uncertainty_reason=critic_in.uncertainty_reason,
    )
    assert gate.invoke_llm is False
    assert gate.reason == "honest_refusal_policy_success"


def test_formatter_coerces_leaked_unknown_without_loop() -> None:
    """Disposition=unknown fed to Formatter coerce → terminal refusal; Critic still rejects raw unknown."""
    coerced = UncertaintyPolicy.coerce_for_downstream("unknown", reason="leaked")
    assert coerced is not None
    assert coerced.disposition == "honest_refusal"
    assert coerced.reason.startswith("unknown_fallback:")
    # Critic gate: planted unknown must not passthrough via coerce wildcard.
    gate = CriticPolicy.decide(
        selected_strategy="reason_only",
        task_kind="knowledge_request",
        continuation_kind=None,
        classification_confidence=0.5,
        confidence_threshold=0.7,
        requires_mcp=False,
        requires_tool_call=False,
        worker_summary="x",
        uncertainty_disposition="unknown",  # type: ignore[arg-type]
        uncertainty_reason="leaked",
    )
    assert gate.invoke_llm is True
    assert gate.reason == "unresolved_unknown_disposition"


def test_unresolved_unknown_never_attached_to_intent() -> None:
    """Pipeline attach uses for_pipeline — residual unknown must not land on contract."""
    raw = UncertaintyPolicy.decide(UncertaintySignals(task_kind="tool_execution", confidence=0.2, retrieval_empty=False))
    assert raw.disposition == "unknown"
    resolved = UncertaintyPolicy.resolved_disposition(raw)
    intent = _fake_intent_with_disposition(resolved)
    assert intent.uncertainty_disposition == "honest_refusal"
    assert intent.uncertainty_disposition != "unknown"
