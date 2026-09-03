# src/palatium_ai/application/agents/formatter/agent.py

"""Formatter — BaseAgent implementation (030)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING, Literal

from pydantic import ValidationError

from palatium_ai.application.agents.formatter.config import REPAIR_ERROR_HEAD
from palatium_ai.application.agents.formatter.parsing import (
    align_formatter_meta,
    build_formatter_user_payload,
    decode_formatter_input,
    parse_formatter_document,
)
from palatium_ai.application.agents.formatter.prompts import FORMATTER_REPAIR_PROMPT, FORMATTER_SYSTEM_PROMPT
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.formatter import FORMATTER_OUTPUT_INVALID
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.llm.models import ChatMessage

if TYPE_CHECKING:
    from palatium_ai.domain.agents.agent_config import AgentConfig

logger = get_logger(__name__)


class FormatterAgent(BaseAgent):
    """Компилирует ContentDocument для UI-рендера."""

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
        ]

    def get_available_tools(self) -> list[str]:
        return []

    @traceable(name="formatter.run")
    async def run(self, input: AgentInput) -> AgentOutput:
        agent_metrics.record_node_execution(self._config.role, "run")
        task_input = decode_formatter_input({**input.context, "_task_id": str(input.task_id)})

        user_payload = build_formatter_user_payload(task_input)
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=FORMATTER_SYSTEM_PROMPT),
            ChatMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
        ]

        try:
            document = await self._generate_document(messages)
            document = align_formatter_meta(document, task_input)
        except Exception:
            logger.exception("formatter document generation failed", task_id=str(input.task_id))
            agent_metrics.record_error(self._config.role, "llm_stage_failure")
            return AgentOutput(
                task_id=input.task_id,
                status="failure",
                confidence=0.0,
                output=_empty_document(),
                error_message=FORMATTER_OUTPUT_INVALID,
            )

        status: Literal["success", "failure", "partial"] = "partial" if task_input.requires_review else "success"
        return AgentOutput(
            task_id=input.task_id,
            status=status,
            confidence=document.meta.confidence,
            output=document,
        )

    async def _generate_document(self, messages: list[ChatMessage]) -> ContentDocument:
        completion = await self._harness.call_llm(
            self._config,
            messages,
            response_format="json_object",
        )
        try:
            return parse_formatter_document(completion.content)
        except (ValidationError, ValueError, json.JSONDecodeError, TypeError) as first_error:
            logger.warning(
                "formatter output invalid, attempting repair",
                error=str(first_error)[:300],
            )
            repair_messages = [
                *messages,
                ChatMessage(role="assistant", content=completion.content),
                ChatMessage(
                    role="user",
                    content=FORMATTER_REPAIR_PROMPT.format(error=str(first_error)[:REPAIR_ERROR_HEAD]),
                ),
            ]
            repair = await self._harness.call_llm(
                self._config,
                repair_messages,
                response_format="json_object",
            )
            return parse_formatter_document(repair.content)


def _empty_document() -> ContentDocument:
    from palatium_ai.domain.content.content_document import DocumentMeta, ParagraphBlock

    return ContentDocument(
        schema_version=1,
        locale="en-US",
        title="",
        blocks=(ParagraphBlock(type="paragraph", text=" "),),
        actions=(),
        meta=DocumentMeta(
            confidence=0.0,
            requires_review=True,
            source_refs=(),
            interaction="none",
        ),
    )
