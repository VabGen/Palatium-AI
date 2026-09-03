# src/palatium_ai/application/agents/formatter/parsing.py

"""Parse and align Formatter LLM JSON."""

from __future__ import annotations

import math

from palatium_ai.application.agents.formatter.config import MIN_PIPELINE_CONFIDENCE, REVIEW_CONFIDENCE_CAP
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.llm.response_parser import parse_llm_response


def parse_formatter_document(raw_content: str) -> ContentDocument:
    """Извлекает JSON и валидирует как ContentDocument."""
    return parse_llm_response(
        raw_content,
        ContentDocument,
        default_factory={
            "meta": {
                "confidence": 0.7,
                "requires_review": False,
                "source_refs": [],
                "interaction": "none",
            }
        },
    )


def align_formatter_meta(document: ContentDocument, task_input: FormatterInput) -> ContentDocument:
    """Синхронизирует meta с critic/HITL флагом (источник истины — пайплайн)."""
    confidence = clamp_confidence(document.meta.confidence)
    if task_input.requires_review:
        confidence = min(confidence, REVIEW_CONFIDENCE_CAP)
    elif confidence < MIN_PIPELINE_CONFIDENCE:
        confidence = MIN_PIPELINE_CONFIDENCE

    interaction = document.meta.interaction
    if (
        task_input.requires_user_choice or task_input.underspecification_kind == "discrete_choice"
    ) and interaction == "none":
        interaction = "choice"

    return document.model_copy(
        update={
            "meta": document.meta.model_copy(
                update={
                    "requires_review": task_input.requires_review,
                    "confidence": confidence,
                    "interaction": interaction,
                }
            )
        }
    )


def clamp_confidence(value: float) -> float:
    """LLM-мусор (NaN/inf/вне диапазона) не должен проехать в UI-контракт."""
    if not math.isfinite(value):
        return 0.0
    return min(max(value, 0.0), 1.0)


def build_formatter_user_payload(task_input: FormatterInput) -> dict[str, object]:
    return {
        "user_text": task_input.context_packet.user_text,
        "task_kind": task_input.context_packet.task_kind,
        "route": task_input.context_packet.route,
        "route_plan": task_input.context_packet.route_plan,
        "context_summary": task_input.context_packet.context_summary,
        "worker_summary": task_input.worker_summary,
        "critic_summary": task_input.critic_summary,
        "requires_review": task_input.requires_review,
        "requires_user_choice": task_input.requires_user_choice,
        "underspecification_kind": task_input.underspecification_kind,
        "revision_feedback": task_input.revision_feedback,
    }


def decode_formatter_input(input_context: dict[str, str]) -> FormatterInput:
    from palatium_ai.domain.agents.context_packet import ContextPacket

    packet = ContextPacket.model_validate_json(input_context["context_packet_json"])
    return FormatterInput(
        task_id=input_context.get("_task_id", packet.task_id),
        context_packet=packet,
        worker_summary=input_context.get("worker_summary") or None,
        critic_summary=input_context.get("critic_summary") or None,
        requires_review=input_context.get("requires_review", "false").lower() == "true",
        requires_user_choice=input_context.get("requires_user_choice", "false").lower() == "true",
        underspecification_kind=input_context.get("underspecification_kind", "none"),
        revision_feedback=input_context.get("revision_feedback") or None,
    )
