# src/palatium_ai/application/agents/formatter/repair.py

"""Formatter schema + locale repair after Markdown stream."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING

from pydantic import ValidationError

from palatium_ai.application.agents.formatter.budgets import repair_max_tokens, was_truncated
from palatium_ai.application.agents.formatter.config import LOCALE_REPAIR_ATTEMPTS, REPAIR_ERROR_HEAD
from palatium_ai.application.agents.formatter.llm_stream import call_formatter_llm, complete
from palatium_ai.application.agents.formatter.markdown_parser import markdown_to_content_document
from palatium_ai.application.agents.formatter.parsing import align_formatter_meta
from palatium_ai.application.agents.formatter.prompts import (
    FORMATTER_LOCALE_REPAIR_PROMPT,
    FORMATTER_REPAIR_PROMPT,
)
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.hop_timings import get_hop_collector
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.llm.json_codec import LLMJSONError
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.domain.policies.hop_budget import HopBudgetPolicy
from palatium_ai.domain.policies.locale import ReplyLocalePolicy

if TYPE_CHECKING:
    from palatium_ai.domain.agents.agent_config import AgentConfig
    from palatium_ai.domain.ports.harness import HarnessPort

logger = get_logger(__name__)

PARSE_ERRORS = (ValidationError, ValueError, json.JSONDecodeError, TypeError, LLMJSONError)


def hop_skip_repairs() -> bool:
    hop = get_hop_collector()
    return (
        hop is not None
        and HopBudgetPolicy.should_skip_formatter_repairs(
            hop_total_ms=hop.total_ms(),
            budget_ms=hop.budget_ms,
        ).degrade
    )


async def generate_document(
    *,
    harness: HarnessPort,
    config: AgentConfig,
    messages: list[ChatMessage],
    task_input: FormatterInput,
    max_tokens: int,
    worker_summary: str = "",
    agent_role: str,
) -> ContentDocument:
    completion, markdown = await call_formatter_llm(
        harness=harness,
        config=config,
        messages=messages,
        max_tokens=max_tokens,
        worker_summary=worker_summary,
    )
    truncated = was_truncated(completion)
    try:
        return markdown_to_content_document(markdown or completion.content, task_input)
    except PARSE_ERRORS as first_error:
        if hop_skip_repairs():
            agent_metrics.record_node_execution(agent_role, "hop_budget_skip_schema_repair")
            raise
        tokens = repair_max_tokens(max_tokens, truncated=truncated)
        logger.warning(
            "formatter markdown invalid, attempting repair",
            error=str(first_error)[:300],
            truncated=truncated,
            repair_max_tokens=tokens,
        )
        repair_messages = [
            *messages,
            ChatMessage(role="assistant", content=markdown or completion.content),
            ChatMessage(
                role="user",
                content=FORMATTER_REPAIR_PROMPT.format(error=str(first_error)[:REPAIR_ERROR_HEAD]),
            ),
        ]
        repair, repair_md = await complete(
            harness=harness,
            config=config,
            messages=repair_messages,
            max_tokens=tokens,
        )
        return markdown_to_content_document(repair_md or repair.content, task_input)


async def maybe_repair_locale_gated(
    *,
    harness: HarnessPort,
    config: AgentConfig,
    messages: list[ChatMessage],
    document: ContentDocument,
    task_input: FormatterInput,
    max_tokens: int,
    agent_role: str,
) -> ContentDocument:
    if hop_skip_repairs():
        agent_metrics.record_node_execution(agent_role, "hop_budget_skip_locale_repair")
        return document
    return await maybe_repair_locale(
        harness=harness,
        config=config,
        messages=messages,
        document=document,
        task_input=task_input,
        max_tokens=max_tokens,
    )


async def maybe_repair_locale(
    *,
    harness: HarnessPort,
    config: AgentConfig,
    messages: list[ChatMessage],
    document: ContentDocument,
    task_input: FormatterInput,
    max_tokens: int,
) -> ContentDocument:
    locale = ReplyLocalePolicy.normalize(task_input.response_locale) or "und"
    if locale == "und":
        return document
    prose = ReplyLocalePolicy.document_prose(document)
    if ReplyLocalePolicy.prose_matches_locale(prose, locale):
        return document
    logger.warning(
        "formatter locale mismatch, attempting repair",
        response_locale=locale,
        document_locale=document.locale,
    )
    current = document
    for _ in range(LOCALE_REPAIR_ATTEMPTS):
        repair_messages = [
            *messages,
            ChatMessage(role="assistant", content=current.plain_text()),
            ChatMessage(
                role="user",
                content=FORMATTER_LOCALE_REPAIR_PROMPT.format(locale=locale),
            ),
        ]
        repair, repair_md = await complete(
            harness=harness,
            config=config,
            messages=repair_messages,
            max_tokens=max_tokens,
        )
        current = align_formatter_meta(
            markdown_to_content_document(repair_md or repair.content, task_input),
            task_input,
        )
        if ReplyLocalePolicy.prose_matches_locale(
            ReplyLocalePolicy.document_prose(current),
            locale,
        ):
            return current
    logger.warning("formatter locale repair exhausted", response_locale=locale)
    return current
