# src/palatium_ai/application/agents/formatter/parsing.py

"""Parse/align Formatter JSON; build minimal cache-friendly user payload (065)."""

from __future__ import annotations

import json
import math

from palatium_ai.application.agents.formatter.cleanup import mechanical_cleanup
from palatium_ai.application.agents.formatter.config import (
    FORMATTER_ATTACHMENT_MAX_CHARS,
    FORMATTER_DIALOG_MAX_CHARS,
    FORMATTER_DIALOG_PER_TURN_MAX_CHARS,
    FORMATTER_SOURCE_MAX_CHARS,
    MIN_PIPELINE_CONFIDENCE,
    REVIEW_CONFIDENCE_CAP,
    FormatterStyleHint,
)
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.content.markdown_blocks import plain_paragraph_count
from palatium_ai.domain.llm.response_parser import parse_llm_response
from palatium_ai.domain.memory.turns import DialogTurnWindow
from palatium_ai.domain.policies.locale import ReplyLocalePolicy
from palatium_ai.domain.policies.types import (
    CONTENT_GENERATION_CAPABILITY,
    DOCUMENT_GENERATION_CAPABILITY,
)


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
    choice_required = task_input.requires_user_choice or task_input.underspecification_kind == "discrete_choice"
    if choice_required and interaction == "none":
        interaction = "choice"
    elif has_attachments and not task_input.requires_user_choice and interaction == "choice":
        # Upload grounds the ask — drop LLM exclusive-menu tags about prior topics (055).
        interaction = "none"
    # Prefer LLM refs when present; always union attachment file citations (W2 G03).
    # Bare UUIDs / attachment:<uuid> are not user-facing — sanitize drops them.
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
    """Minimal hot payload: final_text + style_hint + task_kind (+ gated extras).

    When worker ``final_text`` is present it is authoritative — do NOT re-dump the
    attachment fence (065). Attachment prose is included only when there is no
    worker source (format_only / social+file), and then clipped.

    Social without a worker draft must NOT put ``user_text`` into ``final_text``:
    that made Formatter echo the greeting as a card instead of replying (055).
    """
    locale = ReplyLocalePolicy.normalize(task_input.response_locale) or "und"
    has_attachments = bool((task_input.context_packet.untrusted_context or "").strip())
    source = _clip(
        mechanical_cleanup((task_input.worker_summary or "").strip()),
        FORMATTER_SOURCE_MAX_CHARS,
    )
    user_text = (task_input.context_packet.user_text or "").strip()
    task_kind = task_input.context_packet.task_kind
    social_synthesis = _needs_social_synthesis(task_kind=task_kind, source=source)
    # Empty final_text signals "compose a reply"; never echo the user's phatic line.
    final_text = "" if social_synthesis else source or mechanical_cleanup(user_text)

    from palatium_ai.domain.policies.formatter_memory_merge import FormatterMemoryMergePolicy

    merge = FormatterMemoryMergePolicy.decide(
        memory_hints=task_input.memory_hints,
        has_source_content=bool(source),
    )
    memory_block = "\n".join(f"- {h}" for h in merge.hints) if merge.hints else ""

    payload: dict[str, object] = {
        "final_text": final_text,
        "style_hint": resolve_style_hint(task_input),
        "task_kind": task_kind,
        "response_locale": locale,
        "format_hints": {
            "requires_review": task_input.requires_review,
            "requires_user_choice": task_input.requires_user_choice,
            "underspecification_kind": task_input.underspecification_kind,
            "revision_feedback": task_input.revision_feedback,
        },
    }
    if not source:
        payload["user_text"] = user_text
        payload["dialog_history"] = _formatter_dialog_block(
            task_input.dialog_window,
            has_attachments=has_attachments,
        )
        if has_attachments:
            payload["attachment_context"] = _clip(
                task_input.context_packet.untrusted_context or "",
                FORMATTER_ATTACHMENT_MAX_CHARS,
            )
    if memory_block:
        payload["memory_hints"] = memory_block
    return payload


def build_formatter_user_message(payload: dict[str, object]) -> str:
    """XML-wrap dynamic JSON (Anthropic/OpenAI: separate instructions from data)."""
    body = json.dumps(payload, ensure_ascii=False)
    return f"<formatter_input>\n{body}\n</formatter_input>"


def resolve_style_hint(task_input: FormatterInput) -> FormatterStyleHint:
    """Compact composition hint — closed Literal, not a phrase list (055).

    Order matters: an explicit user decision (choice / clarify / reformat / revise)
    wins; then social synthesis (no worker draft); then generation tags from Intent;
    then the worker answer's own shape — a single structure-free paragraph is shown
    as prose, never compiled into sections.
    """
    if task_input.requires_user_choice or task_input.underspecification_kind == "discrete_choice":
        return "choice_cards"
    if task_input.underspecification_kind == "open_text":
        return "clarify_open"
    source = (task_input.worker_summary or "").strip()
    if _needs_social_synthesis(
        task_kind=task_input.context_packet.task_kind,
        source=source,
    ):
        return "social_reply"
    if task_input.context_packet.task_kind == "response_formatting":
        return "restructure_sections_icons"
    if (task_input.revision_feedback or "").strip():
        return "revise_keep_structure"
    caps = {cap.strip().lower() for cap in task_input.context_packet.candidate_capabilities}
    if DOCUMENT_GENERATION_CAPABILITY in caps:
        return "document_generation"
    if CONTENT_GENERATION_CAPABILITY in caps:
        return "content_generation"
    if source and plain_paragraph_count(source) == 1:
        return "plain_text"
    return "brand_sections_icons"


def _needs_social_synthesis(*, task_kind: str, source: str) -> bool:
    """Live social has no worker draft — Formatter must compose the reply, not echo."""
    return task_kind == "social_conversation" and not source.strip()


def _formatter_dialog_block(
    window: DialogTurnWindow | None,
    *,
    has_attachments: bool,
) -> str:
    if window is None or not window.turns:
        return "(no prior turns)"
    # File-grounded turns: prior assistant answers about other uploads must not
    # compete with the current fence (cross-file bleed). Keep user turns only.
    if has_attachments:
        user_turns = tuple(turn for turn in window.turns if turn.role == "user")
        window = window.model_copy(update={"turns": user_turns}) if user_turns else None
        if window is None or not window.turns:
            return "(no prior turns)"
    return window.as_prompt_block(
        max_chars=FORMATTER_DIALOG_MAX_CHARS,
        per_turn_max_chars=FORMATTER_DIALOG_PER_TURN_MAX_CHARS,
    )


def _clip(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars <= 24:
        return text[:max_chars]
    head = max_chars // 2
    tail = max_chars - head - 15
    return f"{text[:head]}\n…[truncated]…\n{text[-tail:]}"


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
