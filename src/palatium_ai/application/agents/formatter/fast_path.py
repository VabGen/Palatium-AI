# src/palatium_ai/application/agents/formatter/fast_path.py

"""Build ContentDocument without Formatter LLM (policy-driven fast path)."""

from __future__ import annotations

from typing import Literal

from palatium_ai.application.agents.formatter.answer_delta import emit_answer_deltas
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
from palatium_ai.domain.policies.types import ExecutionStrategy, TaskKind

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

    Only the passthrough case skips the LLM (``FormatterFastPathPolicy``);
    ``selected_strategy`` is kept for call-site ABI — presentation soft-degrade is
    not driven by strategy (055).
    """
    _ = selected_strategy
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

    emit_answer_deltas(source)
    document, emit_mode = aligned_document_from_source(source, task_input=task_input)
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


def _passthrough_signals(
    source: str,
    *,
    task_input: FormatterInput,
    task_kind: TaskKind | str | None,
    worker_confidence: float | None,
) -> FormatterPassthroughSignals:
    cleaned = mechanical_cleanup(source).strip()
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
        underspecification_kind=task_input.underspecification_kind,
    )
