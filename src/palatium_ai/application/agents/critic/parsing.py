# src/palatium_ai/application/agents/critic/parsing.py

"""Parse Critic LLM JSON."""

from __future__ import annotations

from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.critic import CriticInput, CriticOutput
from palatium_ai.domain.llm.json_codec import loads_llm_json

_SUMMARY_MAX_CHARS = 2000


def coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def coerce_score(value: object, default: float = 0.0) -> int:
    if not isinstance(value, (int, float, str)):
        return int(default)
    try:
        score = float(value)
    except TypeError, ValueError:
        return int(default)
    if score != score or score in (float("inf"), float("-inf")):
        return int(default)
    return int(min(max(score, 0.0), 10.0))


def parse_critic_output(raw_content: str) -> CriticOutput:
    payload = loads_llm_json(raw_content)
    if not isinstance(payload, dict):
        raise ValueError("Critic JSON must be an object")

    raw_summary = payload.get("summary", "No summary provided")
    summary = str(raw_summary).strip() or "No summary provided"
    if len(summary) > _SUMMARY_MAX_CHARS:
        summary = summary[:_SUMMARY_MAX_CHARS].rstrip() + "…"

    return CriticOutput(
        accuracy_score=coerce_score(payload.get("accuracy_score")),
        safety_score=coerce_score(payload.get("safety_score")),
        requires_review=coerce_bool(payload.get("requires_review")),
        summary=summary,
    )


def confidence_from_scores(output: CriticOutput) -> float:
    return min(max((output.accuracy_score / 10 + output.safety_score / 10) / 2, 0.0), 1.0)


def decode_critic_input(input_context: dict[str, str]) -> CriticInput:
    from palatium_ai.domain.agents.execution import ExecutionStrategy

    packet = ContextPacket.model_validate_json(input_context["context_packet_json"])
    strategy_raw = input_context.get("selected_strategy", "reason_only")
    strategy: ExecutionStrategy = strategy_raw  # type: ignore[assignment]
    continuation = input_context.get("continuation_kind") or None
    try:
        user_input_chars = int(input_context.get("user_input_chars", "0"))
    except ValueError:
        user_input_chars = 0
    try:
        classification_confidence = float(input_context["classification_confidence"])
    except KeyError, ValueError:
        classification_confidence = 0.0

    return CriticInput(
        task_id=input_context.get("_task_id", packet.task_id),
        context_packet=packet,
        classification_confidence=classification_confidence,
        classification_reasoning=input_context.get("classification_reasoning", "n/a"),
        worker_summary=input_context.get("worker_summary") or None,
        selected_strategy=strategy,
        continuation_kind=continuation,
        user_input_chars=user_input_chars,
    )
