# src/palatium_ai/application/agents/formatter/fallback.py

"""Formatter hard-failure and deterministic emergency emit."""

from __future__ import annotations

from typing import Any

from palatium_ai.application.agents.formatter.deterministic import aligned_document_from_source
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.formatter import FORMATTER_OUTPUT_INVALID, FormatterInput
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.content.content_document import DocumentMeta, ParagraphBlock
from palatium_ai.domain.policies.locale import ReplyLocalePolicy

logger = get_logger(__name__)


def invalid_output(*, input: AgentInput, task_input: FormatterInput, agent_role: str) -> AgentOutput:
    """Model output that stays invalid after repair is a failure, not a synthetic document."""
    logger.exception("formatter document invalid after repair", task_id=str(input.task_id))
    agent_metrics.record_error(agent_role, "llm_stage_failure")
    return AgentOutput(
        task_id=input.task_id,
        status="failure",
        confidence=0.0,
        output=empty_document(task_input.response_locale),
        error_message=FORMATTER_OUTPUT_INVALID,
    )


def failure_or_fallback(
    *,
    input: AgentInput,
    task_input: FormatterInput,
    user_payload: dict[str, Any],
    max_tokens: int,
    agent_role: str,
) -> AgentOutput:
    fallback = fallback_document(task_input, user_payload)
    if fallback is not None:
        agent_metrics.record_node_execution(agent_role, "emit:fallback_deterministic")
        logger.warning(
            "formatter.llm_fallback_deterministic",
            task_id=str(input.task_id),
            max_tokens=max_tokens,
        )
        return AgentOutput(
            task_id=input.task_id,
            status="partial",
            confidence=fallback.meta.confidence,
            output=fallback,
            error_message=None,
        )
    return AgentOutput(
        task_id=input.task_id,
        status="failure",
        confidence=0.0,
        output=empty_document(task_input.response_locale),
        error_message=FORMATTER_OUTPUT_INVALID,
    )


def fallback_document(
    task_input: FormatterInput,
    user_payload: dict[str, Any],
) -> ContentDocument | None:
    """Emergency deterministic emit when Formatter LLM truncates/fails."""
    source = str(user_payload.get("final_text") or task_input.worker_summary or "").strip()
    if not source:
        return None
    document, _mode = aligned_document_from_source(source, task_input=task_input)
    return document


def empty_document(response_locale: str) -> ContentDocument:
    locale = ReplyLocalePolicy.normalize(response_locale) or "und"
    return ContentDocument(
        schema_version=1,
        locale=locale,
        title=None,
        blocks=(ParagraphBlock(type="paragraph", text=" "),),
        actions=(),
        meta=DocumentMeta(
            confidence=0.0,
            requires_review=True,
            source_refs=(),
            interaction="none",
        ),
    )
