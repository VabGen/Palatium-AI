# src/palatium_ai/application/agents/critic/parsing.py

"""Decode Critic input; derive confidence from scores.

Critic LLM output is decoded via provider structured output
(``response_format="json_schema"`` + ``response_model=CriticOutput``) inside the
agent, so no manual JSON coercion lives here: the harness/model guarantees the
shape or the call fails loudly.
"""

from __future__ import annotations

from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.critic import CriticInput, CriticOutput


def confidence_from_scores(output: CriticOutput) -> float:
    return min(max((output.accuracy_score / 10 + output.safety_score / 10) / 2, 0.0), 1.0)


def decode_critic_input(input_context: dict[str, str]) -> CriticInput:
    from palatium_ai.domain.agents.execution import ExecutionStrategy

    packet = ContextPacket.model_validate_json(input_context["context_packet_json"])
    strategy_raw = input_context.get("selected_strategy", "reason_only")
    strategy: ExecutionStrategy = strategy_raw  # type: ignore[assignment]  # context собран из Literal-реестра (017)
    continuation = input_context.get("continuation_kind") or None
    try:
        user_input_chars = int(input_context.get("user_input_chars", "0"))
    except ValueError:
        user_input_chars = 0
    try:
        classification_confidence = float(input_context["classification_confidence"])
    except KeyError, ValueError:
        classification_confidence = 0.0
    worker_confidence_raw = input_context.get("worker_confidence", "")
    worker_confidence: float | None
    if worker_confidence_raw.strip() == "":
        worker_confidence = None
    else:
        try:
            worker_confidence = float(worker_confidence_raw)
        except ValueError:
            worker_confidence = None

    return CriticInput(
        task_id=input_context.get("_task_id", packet.task_id),
        context_packet=packet,
        classification_confidence=classification_confidence,
        classification_reasoning=input_context.get("classification_reasoning", "n/a"),
        worker_summary=input_context.get("worker_summary") or None,
        selected_strategy=strategy,
        continuation_kind=continuation,
        user_input_chars=user_input_chars,
        worker_confidence=worker_confidence,
    )
