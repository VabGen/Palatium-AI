# src/palatium_ai/application/agents/formatter/agent.py

"""Formatter — BaseAgent implementation (030).

Pipeline: minimal payload → cacheable system + XML user → stream GFM Markdown →
parse to ContentDocument → align meta → optional locale repair.
On hard failure: deterministic fallback (better than empty/red UI).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from palatium_ai.application.agents.formatter.budgets import formatter_max_tokens, repair_max_tokens
from palatium_ai.application.agents.formatter.fallback import failure_or_fallback, invalid_output
from palatium_ai.application.agents.formatter.llm_stream import (
    FIRST_TOKEN_FALLBACK_SECONDS,
    first_token_fallback_watch,
)
from palatium_ai.application.agents.formatter.parsing import (
    align_formatter_meta,
    build_formatter_user_message,
    build_formatter_user_payload,
    decode_formatter_input,
)
from palatium_ai.application.agents.formatter.prompts import FORMATTER_SYSTEM_PROMPT
from palatium_ai.application.agents.formatter.repair import (
    PARSE_ERRORS,
    generate_document,
    maybe_repair_locale_gated,
)
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.domain.policies.locale import ReplyLocalePolicy

if TYPE_CHECKING:
    from palatium_ai.domain.agents.agent_config import AgentConfig

logger = get_logger(__name__)

# Re-exports for unit tests that import / monkeypatch helpers via this module.
_first_token_fallback_watch = first_token_fallback_watch
_repair_max_tokens = repair_max_tokens
_FIRST_TOKEN_FALLBACK_SECONDS = FIRST_TOKEN_FALLBACK_SECONDS


class FormatterAgent(BaseAgent):
    """Compiles ContentDocument for UI render from a streamed Markdown draft."""

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
        style_hint = user_payload.get("style_hint")
        max_tokens = formatter_max_tokens(
            user_message,
            style_hint=str(style_hint) if isinstance(style_hint, str) else None,
        )

        try:
            document = await generate_document(
                harness=self._harness,
                config=self._config,
                messages=messages,
                task_input=task_input,
                max_tokens=max_tokens,
                worker_summary=task_input.worker_summary or "",
                agent_role=self._config.role,
            )
            document = align_formatter_meta(document, task_input)
            document = await maybe_repair_locale_gated(
                harness=self._harness,
                config=self._config,
                messages=messages,
                document=document,
                task_input=task_input,
                max_tokens=max_tokens,
                agent_role=self._config.role,
            )
        except PARSE_ERRORS:
            return invalid_output(input=input, task_input=task_input, agent_role=self._config.role)
        except Exception:
            logger.exception("formatter document generation failed", task_id=str(input.task_id))
            agent_metrics.record_error(self._config.role, "llm_stage_failure")
            return failure_or_fallback(
                input=input,
                task_input=task_input,
                user_payload=user_payload,
                max_tokens=max_tokens,
                agent_role=self._config.role,
            )

        agent_metrics.record_node_execution(self._config.role, "emit:llm")
        logger.info(
            "formatter.llm_path",
            formatter_mode="llm_markdown",
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
