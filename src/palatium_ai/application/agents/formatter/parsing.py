# src/palatium_ai/application/agents/formatter/parsing.py

"""Parse and align Formatter LLM JSON."""

from __future__ import annotations

import json
import math

from palatium_ai.application.agents.formatter.config import MIN_PIPELINE_CONFIDENCE, REVIEW_CONFIDENCE_CAP
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.llm.response_parser import parse_llm_response
from palatium_ai.domain.memory.turns import DialogTurnWindow
from palatium_ai.domain.policies.locale import ReplyLocalePolicy


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
    """Синхронизирует meta/locale с пайплайном (locale pin — source of truth)."""
    from palatium_ai.domain.attachments.citations import (
        citation_refs_from_untrusted_context,
        sanitize_source_refs,
    )

    confidence = clamp_confidence(document.meta.confidence)
    if task_input.requires_review:
        confidence = min(confidence, REVIEW_CONFIDENCE_CAP)
    elif confidence < MIN_PIPELINE_CONFIDENCE:
        confidence = MIN_PIPELINE_CONFIDENCE

    locale = ReplyLocalePolicy.normalize(task_input.response_locale) or "und"
    attachment_refs = citation_refs_from_untrusted_context(task_input.context_packet.untrusted_context)
    has_attachments = bool((task_input.context_packet.untrusted_context or "").strip())

    interaction = document.meta.interaction
    if (
        task_input.requires_user_choice or task_input.underspecification_kind == "discrete_choice"
    ) and interaction == "none":
        interaction = "choice"
    elif has_attachments and not task_input.requires_user_choice and interaction == "choice":
        # Upload grounds the ask — drop LLM exclusive-menu tags about prior topics (055).
        interaction = "none"
    # Prefer LLM refs when present; always union attachment file/page citations (W2 G03).
    # Bare UUIDs are not user-facing citations — drop them (LLM often echoes fence ids).
    merged_refs = sanitize_source_refs((*document.meta.source_refs, *attachment_refs))

    return document.model_copy(
        update={
            "locale": locale,
            "meta": document.meta.model_copy(
                update={
                    "requires_review": task_input.requires_review,
                    "confidence": confidence,
                    "interaction": interaction,
                    "source_refs": merged_refs,
                }
            ),
        }
    )


def clamp_confidence(value: float) -> float:
    """LLM-мусор (NaN/inf/вне диапазона) не должен проехать в UI-контракт."""
    if not math.isfinite(value):
        return 0.0
    return min(max(value, 0.0), 1.0)


def build_formatter_user_payload(task_input: FormatterInput) -> dict[str, object]:
    locale = ReplyLocalePolicy.normalize(task_input.response_locale) or "und"
    has_attachments = bool((task_input.context_packet.untrusted_context or "").strip())
    dialog_block = "(no prior turns)"
    window: DialogTurnWindow | None = task_input.dialog_window
    if window is not None and window.turns:
        # File-grounded turns: prior assistant answers about other uploads must not
        # compete with the current fence (cross-file bleed). Keep user turns only.
        if has_attachments:
            user_turns = tuple(turn for turn in window.turns if turn.role == "user")
            window = window.model_copy(update={"turns": user_turns}) if user_turns else None
        if window is not None and window.turns:
            dialog_block = window.as_prompt_block(
                max_chars=8000,
                per_turn_max_chars=1200,
            )

    memory_block = ""
    if task_input.memory_hints:
        memory_block = "\n".join(f"- {h}" for h in task_input.memory_hints[:4])

    return {
        "response_locale": locale,
        "user_text": task_input.context_packet.user_text,
        "task_kind": task_input.context_packet.task_kind,
        "route": task_input.context_packet.route,
        "route_plan": task_input.context_packet.route_plan,
        "context_summary": task_input.context_packet.context_summary,
        "attachment_context": task_input.context_packet.untrusted_context,
        "worker_summary": task_input.worker_summary,
        "critic_summary": task_input.critic_summary,
        "requires_review": task_input.requires_review,
        "requires_user_choice": task_input.requires_user_choice,
        "underspecification_kind": task_input.underspecification_kind,
        "revision_feedback": task_input.revision_feedback,
        "dialog_history": dialog_block,
        "memory_hints": memory_block,
    }


def decode_formatter_input(input_context: dict[str, str]) -> FormatterInput:
    """Восстанавливает FormatterInput из AgentInput.context."""
    from palatium_ai.domain.agents.context_packet import ContextPacket
    from palatium_ai.domain.memory.turns import DialogTurnWindow

    packet = ContextPacket.model_validate_json(input_context["context_packet_json"])
    locale = ReplyLocalePolicy.normalize(input_context.get("response_locale")) or "und"

    dialog_window: DialogTurnWindow | None = None
    raw_dw = input_context.get("dialog_window_json") or ""
    if raw_dw:
        try:
            dialog_window = DialogTurnWindow.model_validate_json(raw_dw)
        except ValueError, TypeError:
            dialog_window = None

    memory_hints: tuple[str, ...] = ()
    raw_mh = input_context.get("memory_hints_json") or "[]"
    try:
        parsed_mh = json.loads(raw_mh)
        if isinstance(parsed_mh, list):
            memory_hints = tuple(str(h) for h in parsed_mh)
    except ValueError, TypeError:
        memory_hints = ()

    return FormatterInput(
        task_id=input_context.get("_task_id", packet.task_id),
        context_packet=packet,
        worker_summary=input_context.get("worker_summary") or "",
        critic_summary=input_context.get("critic_summary") or "",
        requires_review=input_context.get("requires_review", "false").lower() == "true",
        requires_user_choice=input_context.get("requires_user_choice", "false").lower() == "true",
        underspecification_kind=input_context.get("underspecification_kind", "none"),
        revision_feedback=input_context.get("revision_feedback") or None,
        response_locale=locale,
        dialog_window=dialog_window,
        memory_hints=memory_hints,
    )
