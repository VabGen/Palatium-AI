# src/palatium_ai/application/agents/formatter/agent.py

"""Formatter — BaseAgent implementation (030).

Pipeline: minimal payload → cacheable system + XML user → stream LLM →
align meta → optional locale repair. On hard failure: deterministic fallback
(better than empty/red UI). Truncation (finish_reason=length) bumps repair budget.
"""

from __future__ import annotations

import json

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError

from palatium_ai.application.agents.formatter.config import (
    FORMATTER_MAX_COMPLETION_TOKENS,
    FORMATTER_MIN_COMPLETION_TOKENS,
    LOCALE_REPAIR_ATTEMPTS,
    REPAIR_ERROR_HEAD,
)
from palatium_ai.application.agents.formatter.parsing import (
    align_formatter_meta,
    build_formatter_user_message,
    build_formatter_user_payload,
    decode_formatter_input,
    parse_formatter_document,
)
from palatium_ai.application.agents.formatter.prompts import (
    FORMATTER_LOCALE_REPAIR_PROMPT,
    FORMATTER_REPAIR_PROMPT,
    FORMATTER_SYSTEM_PROMPT,
)
from palatium_ai.core.context.tokens import count_tokens
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.hop_timings import get_hop_collector
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.formatter import FORMATTER_OUTPUT_INVALID, FormatterInput
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.llm.errors import StructuredOutputUnsupportedError
from palatium_ai.domain.llm.json_codec import LLMJSONError
from palatium_ai.domain.llm.models import ChatMessage, LLMCompletion, LLMResponseFormat
from palatium_ai.domain.policies.hop_budget import HopBudgetPolicy
from palatium_ai.domain.policies.locale import ReplyLocalePolicy

if TYPE_CHECKING:
    from palatium_ai.domain.agents.agent_config import AgentConfig

logger = get_logger(__name__)

_PARSE_ERRORS = (ValidationError, ValueError, json.JSONDecodeError, TypeError, LLMJSONError)
_LENGTH_FINISH = frozenset({"length", "max_tokens"})
_Delta = Callable[[str], object]


def formatter_max_tokens(payload_text: str) -> int:
    """Completion budget from full user payload (not final_text alone)."""
    estimated = count_tokens(payload_text) * 2
    return min(max(estimated, FORMATTER_MIN_COMPLETION_TOKENS), FORMATTER_MAX_COMPLETION_TOKENS)


def _repair_max_tokens(base: int, *, truncated: bool) -> int:
    """On length truncation, double budget once (still capped)."""
    if not truncated:
        return base
    return min(max(base * 2, FORMATTER_MIN_COMPLETION_TOKENS), FORMATTER_MAX_COMPLETION_TOKENS)


def _was_truncated(completion: LLMCompletion) -> bool:
    reason = (completion.finish_reason or "").strip().lower()
    return reason in _LENGTH_FINISH


class FormatterAgent(BaseAgent):
    """Компилирует ContentDocument для UI-рендера (presentation LLM)."""

    @property
    def config(self) -> AgentConfig:
        return self._config

    def get_required_context_keys(self) -> list[str]:
        return [
            "context_packet_json",
            "worker_summary",
            "critic_summary",
            "requires_review",
            "requires_user_choice",
            "underspecification_kind",
            "revision_feedback",
            "response_locale",
        ]

    def get_available_tools(self) -> list[str]:
        return []

    @traceable(name="formatter.run")
    async def run(self, input: AgentInput) -> AgentOutput:
        agent_metrics.record_node_execution(self._config.role, "run")
        task_input = decode_formatter_input({**input.context, "_task_id": str(input.task_id)})
        user_payload = build_formatter_user_payload(task_input)
        user_message = build_formatter_user_message(user_payload)
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=FORMATTER_SYSTEM_PROMPT),
            ChatMessage(role="user", content=user_message),
        ]
        max_tokens = formatter_max_tokens(user_message)

        try:
            document = await self._generate_document(messages, max_tokens=max_tokens)
            document = align_formatter_meta(document, task_input)
            document = await self._maybe_repair_locale_gated(
                messages,
                document,
                task_input,
                max_tokens=max_tokens,
            )
        except _PARSE_ERRORS:
            return self._invalid_output(input, task_input)
        except Exception:
            logger.exception("formatter document generation failed", task_id=str(input.task_id))
            agent_metrics.record_error(self._config.role, "llm_stage_failure")
            return self._failure_or_fallback(input, task_input, user_payload, max_tokens=max_tokens)

        agent_metrics.record_node_execution(self._config.role, "emit:llm")
        logger.info(
            "formatter.llm_path",
            formatter_mode="llm",
            task_id=str(input.task_id),
            max_tokens=max_tokens,
            final_text_chars=len(str(user_payload.get("final_text") or "")),
            user_payload_chars=len(user_message),
            style_hint=user_payload.get("style_hint"),
        )
        status: Literal["success", "partial"] = "partial" if task_input.requires_review else "success"
        return AgentOutput(
            task_id=input.task_id,
            status=status,
            confidence=document.meta.confidence,
            output=document,
        )

    async def verify(self, output: AgentOutput) -> bool:
        if not isinstance(output.output, ContentDocument):
            return False
        return ReplyLocalePolicy.prose_matches_locale(
            ReplyLocalePolicy.document_prose(output.output),
            output.output.locale,
        )

    async def _generate_document(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int,
    ) -> ContentDocument:
        completion = await self._call_formatter_llm(messages, max_tokens=max_tokens)
        truncated = _was_truncated(completion)
        try:
            return parse_formatter_document(completion.content)
        except _PARSE_ERRORS as first_error:
            if _hop_skip_repairs():
                agent_metrics.record_node_execution(self._config.role, "hop_budget_skip_schema_repair")
                raise
            repair_tokens = _repair_max_tokens(max_tokens, truncated=truncated)
            logger.warning(
                "formatter output invalid, attempting repair",
                error=str(first_error)[:300],
                truncated=truncated,
                repair_max_tokens=repair_tokens,
            )
            repair_messages = [
                *messages,
                ChatMessage(role="assistant", content=completion.content),
                ChatMessage(
                    role="user",
                    content=FORMATTER_REPAIR_PROMPT.format(error=str(first_error)[:REPAIR_ERROR_HEAD]),
                ),
            ]
            repair = await self._complete(repair_messages, max_tokens=repair_tokens)
            return parse_formatter_document(repair.content)

    async def _call_formatter_llm(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int,
    ) -> LLMCompletion:
        """Primary formatter LLM. Raw JSON deltas only when debug streaming is on."""
        from palatium_ai.application.services.turn_sse_bridge import get_turn_sse_bridge
        from palatium_ai.core.config import get_settings

        bridge = get_turn_sse_bridge()
        if bridge is None or not get_settings().formatter.debug_stream_deltas:
            return await self._complete(messages, max_tokens=max_tokens)

        async def _on_delta(chunk: str) -> None:
            await bridge.emit({"event": "formatter_delta", "delta": chunk})

        return await self._complete(messages, max_tokens=max_tokens, on_delta=_on_delta)

    async def _complete(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int,
        on_delta: _Delta | None = None,
    ) -> LLMCompletion:
        """json_schema first. Fall back to json_object only when the provider refuses the mode."""
        try:
            return await self._dispatch(
                messages,
                max_tokens=max_tokens,
                on_delta=on_delta,
                response_format="json_schema",
            )
        except StructuredOutputUnsupportedError:
            logger.warning("provider dropped json_schema, falling back to json_object")
            return await self._dispatch(
                messages,
                max_tokens=max_tokens,
                on_delta=on_delta,
                response_format="json_object",
            )

    async def _dispatch(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int,
        on_delta: _Delta | None,
        response_format: LLMResponseFormat,
    ) -> LLMCompletion:
        response_model = ContentDocument if response_format == "json_schema" else None
        if on_delta is None:
            return await self._harness.call_llm(
                self._config,
                messages,
                response_format=response_format,
                response_model=response_model,
                max_tokens=max_tokens,
            )
        return await self._harness.call_llm_stream(
            self._config,
            messages,
            response_format=response_format,
            response_model=response_model,
            on_delta=on_delta,
            max_tokens=max_tokens,
        )

    async def _maybe_repair_locale_gated(
        self,
        messages: list[ChatMessage],
        document: ContentDocument,
        task_input: FormatterInput,
        *,
        max_tokens: int,
    ) -> ContentDocument:
        if _hop_skip_repairs():
            agent_metrics.record_node_execution(self._config.role, "hop_budget_skip_locale_repair")
            return document
        return await self._maybe_repair_locale(
            messages,
            document,
            task_input,
            max_tokens=max_tokens,
        )

    async def _maybe_repair_locale(
        self,
        messages: list[ChatMessage],
        document: ContentDocument,
        task_input: FormatterInput,
        *,
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
                ChatMessage(role="assistant", content=current.model_dump_json()),
                ChatMessage(
                    role="user",
                    content=FORMATTER_LOCALE_REPAIR_PROMPT.format(locale=locale),
                ),
            ]
            repair = await self._complete(repair_messages, max_tokens=max_tokens)
            current = align_formatter_meta(parse_formatter_document(repair.content), task_input)
            if ReplyLocalePolicy.prose_matches_locale(
                ReplyLocalePolicy.document_prose(current),
                locale,
            ):
                return current
        logger.warning("formatter locale repair exhausted", response_locale=locale)
        return current

    def _invalid_output(self, input: AgentInput, task_input: FormatterInput) -> AgentOutput:
        """Model JSON that stays invalid after repair is a failure, not a synthetic document."""
        logger.exception("formatter document invalid after repair", task_id=str(input.task_id))
        agent_metrics.record_error(self._config.role, "llm_stage_failure")
        return AgentOutput(
            task_id=input.task_id,
            status="failure",
            confidence=0.0,
            output=_empty_document(task_input.response_locale),
            error_message=FORMATTER_OUTPUT_INVALID,
        )

    def _failure_or_fallback(
        self,
        input: AgentInput,
        task_input: FormatterInput,
        user_payload: dict[str, Any],
        *,
        max_tokens: int,
    ) -> AgentOutput:
        fallback = _fallback_document(task_input, user_payload)
        if fallback is not None:
            agent_metrics.record_node_execution(self._config.role, "emit:fallback_deterministic")
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
            output=_empty_document(task_input.response_locale),
            error_message=FORMATTER_OUTPUT_INVALID,
        )


def _hop_skip_repairs() -> bool:
    hop = get_hop_collector()
    return (
        hop is not None
        and HopBudgetPolicy.should_skip_formatter_repairs(
            hop_total_ms=hop.total_ms(),
            budget_ms=hop.budget_ms,
        ).degrade
    )


def _fallback_document(
    task_input: FormatterInput,
    user_payload: dict[str, Any],
) -> ContentDocument | None:
    """Emergency deterministic emit when Formatter LLM truncates/fails."""
    from palatium_ai.application.agents.formatter.deterministic import aligned_document_from_source

    source = str(user_payload.get("final_text") or task_input.worker_summary or "").strip()
    if not source:
        return None
    document, _mode = aligned_document_from_source(source, task_input=task_input)
    return document


def _empty_document(response_locale: str) -> ContentDocument:
    from palatium_ai.domain.content.content_document import DocumentMeta, ParagraphBlock

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
