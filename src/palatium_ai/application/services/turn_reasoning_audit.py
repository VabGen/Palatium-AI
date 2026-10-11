# src/palatium_ai/application/services/turn_reasoning_audit.py

"""One structured ``agent.turn.reasoning`` record per turn (040, H1).

Answers "why did the assistant do that" from logs alone: which axes Intent and
Contextualizer produced, what Continuity/ClarificationGate decided, which memory and
attachments reached the context, and which HITL cards were minted. Memory texts are
never logged (PII, 060) — only tier/kind/score/confidence plus a short digest that
correlates with ``memory.entries`` without exposing content.
"""

from __future__ import annotations

import hashlib

from typing import TYPE_CHECKING

from palatium_ai.domain.attachments.citations import citation_refs_from_untrusted_context

if TYPE_CHECKING:
    from palatium_ai.application.orchestration.state import AgentGraphState
    from palatium_ai.domain.agents.formatter import FormatterTaskResult

_REASONING_MAX_CHARS = 400
_DIGEST_CHARS = 12


def turn_reasoning_fields(
    final_state: AgentGraphState,
    formatted: FormatterTaskResult,
    *,
    selected_strategy: str,
) -> dict[str, object]:
    """Flat, PII-free fields for the per-turn reasoning audit event."""
    fields: dict[str, object] = {"selected_strategy": selected_strategy}
    fields.update(_intent_fields(final_state))
    fields.update(_continuation_fields(final_state))
    fields.update(_routing_fields(final_state))
    fields["memory_hits"] = _memory_hits(final_state)
    untrusted = str(final_state.get("untrusted_context") or "")
    fields["attachment_refs"] = list(citation_refs_from_untrusted_context(untrusted))
    fields["hitl_cards"] = [card.purpose for card in formatted.hitl_cards]
    fields["formatter_status"] = formatted.status
    return fields


def _intent_fields(state: AgentGraphState) -> dict[str, object]:
    classification = state.get("classification")
    raw = classification.output if classification is not None else None
    if raw is None:
        return {"intent_task_kind": None, "intent_confidence": None, "intent_status": "missing"}
    return {
        "intent_task_kind": raw.task_kind,
        "intent_underspecification_kind": raw.underspecification_kind,
        "intent_requires_user_choice": raw.requires_user_choice,
        "intent_confidence": round(float(raw.confidence), 3),
        "intent_status": classification.status if classification is not None else "missing",
    }


def _continuation_fields(state: AgentGraphState) -> dict[str, object]:
    contextualization = state.get("contextualization")
    ctx = contextualization.output if contextualization is not None else None
    if ctx is None:
        return {"continuation_kind": None}
    return {
        "continuation_kind": ctx.continuation_kind,
        "refers_to_prior": ctx.refers_to_prior,
        "slot_filled_by_prior": ctx.choice_slot_filled,
        "continuation_confidence": round(float(ctx.confidence), 3),
    }


def _routing_fields(state: AgentGraphState) -> dict[str, object]:
    routing = state.get("routing_intent")
    if routing is None:
        return {"task_kind": None}
    return {
        "task_kind": routing.task_kind,
        "underspecification_kind": routing.underspecification_kind,
        "requires_user_choice": routing.requires_user_choice,
        "trust_prior_for_workers": routing.trust_prior_for_workers,
        "suppress_intent_hitl": routing.suppress_intent_hitl,
        "has_prior_context": routing.prior_context is not None,
        "routing_reasoning": routing.reasoning[:_REASONING_MAX_CHARS],
    }


def _memory_hits(state: AgentGraphState) -> list[dict[str, object]]:
    recall = state.get("memory_recall")
    if recall is None:
        return []
    return [
        {
            "source": hit.source,
            "kind": hit.kind,
            "score": hit.score,
            "confidence": round(float(hit.confidence), 3),
            "digest": hashlib.sha256(hit.text.encode("utf-8")).hexdigest()[:_DIGEST_CHARS],
        }
        for hit in recall.hits
    ]
