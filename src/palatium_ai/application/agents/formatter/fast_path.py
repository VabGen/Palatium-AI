# src/palatium_ai/application/agents/formatter/fast_path.py

"""Build ContentDocument without Formatter LLM (policy-driven fast path)."""

from __future__ import annotations

from typing import Literal

from palatium_ai.application.agents.formatter.answer_delta import emit_content_document
from palatium_ai.application.agents.formatter.cleanup import mechanical_cleanup
from palatium_ai.application.agents.formatter.config import (
    FORMATTER_PASSTHROUGH_MAX_CHARS,
    MIN_PIPELINE_CONFIDENCE,
)
from palatium_ai.application.agents.formatter.deterministic import (
    aligned_document_from_source,
    document_from_source_content,
)
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.formatter import FormatterInput, FormatterTaskResult
from palatium_ai.domain.content.markdown_blocks import plain_paragraph_count
from palatium_ai.domain.memory.tool_output import contains_untrusted_tool_output
from palatium_ai.domain.policies.formatter_fast_path import (
    FormatterFastPathPolicy,
    FormatterPassthroughSignals,
)
from palatium_ai.domain.policies.locale import ReplyLocalePolicy
from palatium_ai.domain.policies.types import (
    VERBATIM_EXTRACTION_CAPABILITY,
    ExecutionStrategy,
    TaskKind,
)

logger = get_logger(__name__)

# Re-export for callers/tests that import from fast_path.
__all__ = [
    "document_from_source_content",
    "try_formatter_fast_path",
]


def try_formatter_fast_path(
    *,
    task_input: FormatterInput,
    task_kind: TaskKind | str | None,
    selected_strategy: ExecutionStrategy | str | None,
    agent_role: str = "formatter",
    worker_confidence: float | None = None,
) -> FormatterTaskResult | None:
    """Return a FormatterTaskResult when policy skips LLM; else None.

    Order: mechanical restructure of a persisted prior document (wave 3) → plain
    passthrough (``FormatterFastPathPolicy``). ``selected_strategy`` is kept for
    call-site ABI — presentation soft-degrade is not driven by strategy (055).
    """
    _ = selected_strategy
    mechanical = _try_mechanical_restructure(task_input, task_kind=task_kind, agent_role=agent_role)
    if mechanical is not None:
        return mechanical

    source = (task_input.worker_summary or "").strip()
    decision = FormatterFastPathPolicy.decide(
        source_content=source,
        requires_user_choice=task_input.requires_user_choice,
        passthrough=_passthrough_signals(
            source,
            task_input=task_input,
            task_kind=task_kind,
            worker_confidence=worker_confidence,
        ),
        passthrough_max_chars=FORMATTER_PASSTHROUGH_MAX_CHARS,
    )
    if not decision.skip_llm:
        return None

    document, emit_mode = aligned_document_from_source(source, task_input=task_input)
    emit_content_document(document)
    agent_metrics.record_node_execution(agent_role, f"fast_path:{decision.reason}")
    agent_metrics.record_node_execution(agent_role, f"emit:{emit_mode}")
    logger.info(
        "formatter.fast_path",
        reason=decision.reason,
        emit_mode=emit_mode,
        formatter_mode="deterministic",
        task_id=task_input.task_id,
        source_chars=len(source),
    )
    status: Literal["success", "partial"] = "partial" if task_input.requires_review else "success"
    return FormatterTaskResult(
        task_id=task_input.task_id,
        agent_role="formatter",
        status=status,
        confidence=document.meta.confidence,
        requires_review=task_input.requires_review,
        output=document,
    )


def _try_mechanical_restructure(
    task_input: FormatterInput,
    *,
    task_kind: TaskKind | str | None,
    agent_role: str,
) -> FormatterTaskResult | None:
    """Reuse/reshape prior ContentDocument without Formatter LLM when safe."""
    from palatium_ai.application.agents.formatter.parsing import align_formatter_meta
    from palatium_ai.application.services.intent_turn_helpers import previous_assistant_document
    from palatium_ai.domain.policies.mechanical_restructure import MechanicalRestructurePolicy
    from palatium_ai.domain.policies.types import RESPONSE_SHAPE_DEFAULT

    if task_input.requires_user_choice or task_input.requires_review:
        return None
    if (task_input.revision_feedback or "").strip():
        return None

    shape = task_input.context_packet.response_shape
    eligible = task_input.transformation == "restructure" or task_kind == "response_formatting" or shape != RESPONSE_SHAPE_DEFAULT
    if not eligible:
        return None

    prior = previous_assistant_document(task_input.dialog_window)
    decision = MechanicalRestructurePolicy.apply(
        prior,
        shape=shape,
        transformation=task_input.transformation,
        task_kind=str(task_kind) if task_kind is not None else None,
    )
    if decision.document is None:
        return None

    document = align_formatter_meta(decision.document, task_input)
    emit_content_document(document)
    agent_metrics.record_node_execution(agent_role, f"fast_path:{decision.reason}")
    agent_metrics.record_node_execution(agent_role, "emit:mechanical_restructure")
    # Closed outcome labels for wave-3 observability (040) — never free-form reasons.
    agent_metrics.record_response_shape(
        shape=shape if shape != RESPONSE_SHAPE_DEFAULT else "auto",
        outcome=_mechanical_shape_outcome(decision.reason),
    )
    logger.info(
        "formatter.mechanical_restructure",
        reason=decision.reason,
        shape=shape,
        transformation=task_input.transformation,
        task_id=task_input.task_id,
    )
    status: Literal["success", "partial"] = "partial" if task_input.requires_review else "success"
    return FormatterTaskResult(
        task_id=task_input.task_id,
        agent_role="formatter",
        status=status,
        confidence=document.meta.confidence,
        requires_review=task_input.requires_review,
        output=document,
    )


def _mechanical_shape_outcome(reason: str) -> str:
    """Map policy reasons onto the closed ``record_response_shape`` outcome set."""
    if reason in {"prior_already_satisfies_shape", "restructure_reuse_prior"}:
        return "mechanical_reuse"
    if reason.startswith("promoted_to_"):
        return "mechanical_promote"
    if reason == "flatten_to_prose":
        return "mechanical_flatten"
    return "mechanical_ok"


def _passthrough_signals(
    source: str,
    *,
    task_input: FormatterInput,
    task_kind: TaskKind | str | None,
    worker_confidence: float | None,
) -> FormatterPassthroughSignals:
    cleaned = mechanical_cleanup(source).strip()
    caps = {cap.strip().lower() for cap in task_input.context_packet.candidate_capabilities}
    return FormatterPassthroughSignals(
        source_chars=len(cleaned),
        worker_confident=worker_confidence is not None and worker_confidence >= MIN_PIPELINE_CONFIDENCE,
        source_is_plain_prose=(
            bool(cleaned) and plain_paragraph_count(cleaned) is not None and not contains_untrusted_tool_output(cleaned)
        ),
        locale_matches=ReplyLocalePolicy.prose_matches_locale(cleaned, task_input.response_locale),
        requires_review=task_input.requires_review,
        revision_requested=bool((task_input.revision_feedback or "").strip()),
        restructure_requested=task_kind == "response_formatting",
        shape_requested=task_input.context_packet.response_shape != "auto",
        underspecification_kind=task_input.underspecification_kind,
        verbatim_requested=VERBATIM_EXTRACTION_CAPABILITY in caps,
    )
