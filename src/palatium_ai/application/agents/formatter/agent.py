# src/palatium_ai/application/agents/formatter/agent.py

"""Formatter — BaseAgent implementation (030).

Two generation contracts, selected by ``FormatterConfig.formatter_mode``:
- ``legacy`` (default): stream GFM Markdown → parse to ContentDocument → align meta
  → optional locale repair. On hard failure: deterministic fallback.
- ``schema_first`` (canary): provider-enforced ``json_schema`` ContentDocument → align
  meta. Falls back to ``legacy`` when the provider refuses structured output or the
  model returns JSON that fails validation.
"""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Literal

from pydantic import ValidationError

from palatium_ai.application.agents.formatter.budgets import formatter_max_tokens, repair_max_tokens
from palatium_ai.application.agents.formatter.fallback import failure_or_fallback
from palatium_ai.application.agents.formatter.llm_stream import (
    FIRST_TOKEN_FALLBACK_SECONDS,
    first_token_fallback_watch,
)
from palatium_ai.application.agents.formatter.parsing import (
    align_formatter_meta,
    build_formatter_user_message,
    build_formatter_user_payload,
    decode_formatter_input,
    formatter_attachment_stats,
)
from palatium_ai.application.agents.formatter.prompts import (
    FORMATTER_SCHEMA_PROMPT,
    FORMATTER_SYSTEM_PROMPT,
)
from palatium_ai.application.agents.formatter.repair import (
    PARSE_ERRORS,
    generate_document,
    maybe_repair_locale_gated,
)
from palatium_ai.core.config.formatter import FormatterMode
from palatium_ai.core.logging import get_logger
from palatium_ai.core.logging.context import user_id_var
from palatium_ai.core.observability.formatter_rollout import resolve_formatter_mode
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.llm.errors import StructuredOutputUnsupportedError
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.domain.policies.locale import ReplyLocalePolicy

if TYPE_CHECKING:
    from palatium_ai.domain.agents.agent_config import AgentConfig
    from palatium_ai.domain.agents.formatter import FormatterInput
    from palatium_ai.domain.ports.harness import HarnessPort

logger = get_logger(__name__)

# Re-exports for unit tests that import / monkeypatch helpers via this module.
_first_token_fallback_watch = first_token_fallback_watch
_repair_max_tokens = repair_max_tokens
_FIRST_TOKEN_FALLBACK_SECONDS = FIRST_TOKEN_FALLBACK_SECONDS


class FormatterAgent(BaseAgent):
    """Compiles ContentDocument for UI render (Markdown or schema-first)."""

    def __init__(
        self,
        harness: HarnessPort,
        config: AgentConfig,
        *,
        mode: FormatterMode = "legacy",
        rollout_pct: int = 100,
    ) -> None:
        super().__init__(harness, config)
        self._mode: FormatterMode = mode
        self._rollout_pct: int = rollout_pct

    @property
    def config(self) -> AgentConfig:
        return self._config

    @property
    def mode(self) -> FormatterMode:
        return self._mode

    @property
    def rollout_pct(self) -> int:
        return self._rollout_pct

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
        effective_mode = resolve_formatter_mode(self._mode, self._rollout_pct, user_id_var.get())
        started = perf_counter()
        try:
            if effective_mode == "schema_first":
                return await self._run_schema_first(input, task_input)
            return await self._run_legacy(input, task_input)
        finally:
            # Mode-split latency for the canary A/B: both cohorts share one process, so
            # comparing schema_first against the legacy baseline needs this label.
            agent_metrics.record_node_execution(
                self._config.role,
                f"formatter:{effective_mode}",
                duration_seconds=perf_counter() - started,
            )

    async def _run_schema_first(self, input: AgentInput, task_input: FormatterInput) -> AgentOutput:
        """Provider-enforced ContentDocument json_schema; legacy Markdown is the fallback."""
        user_payload = build_formatter_user_payload(task_input)
        user_message = build_formatter_user_message(user_payload)
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=FORMATTER_SCHEMA_PROMPT),
            ChatMessage(role="user", content=user_message),
        ]
        style_hint = user_payload.get("style_hint")
        max_tokens = formatter_max_tokens(
            user_message,
            style_hint=str(style_hint) if isinstance(style_hint, str) else None,
            final_text_len=len(str(user_payload.get("final_text") or "")),
        )
        try:
            completion = await self._harness.call_llm(
                self._config,
                messages,
                response_format="json_schema",
                response_model=ContentDocument,
                max_tokens=max_tokens,
            )
            document = ContentDocument.model_validate_json(completion.content)
        except StructuredOutputUnsupportedError:
            logger.warning("formatter.schema_first.unsupported", task_id=str(input.task_id))
            agent_metrics.record_node_execution(self._config.role, "schema_first:unsupported")
            return await self._run_legacy(input, task_input)
        except ValidationError as exc:
            logger.warning(
                "formatter.schema_first.invalid_json",
                task_id=str(input.task_id),
                error=str(exc)[:300],
            )
            agent_metrics.record_node_execution(self._config.role, "schema_first:invalid_json")
            return await self._run_legacy(input, task_input)
        except Exception:
            # Provider/timeout failure: same graceful deterministic fallback as legacy.
            logger.exception("formatter schema_first generation failed", task_id=str(input.task_id))
            agent_metrics.record_error(self._config.role, "schema_first_llm_stage_failure")
            return failure_or_fallback(
                input=input,
                task_input=task_input,
                user_payload=user_payload,
                max_tokens=max_tokens,
                agent_role=self._config.role,
            )

        if not document.blocks and str(user_payload.get("final_text") or "").strip():
            # The schema permits an empty `blocks` (and the provider does not enforce
            # `required`), so the model can silently drop a non-empty answer. Reopen the
            # legacy path, which renders the worker draft instead of an empty document.
            logger.warning("formatter.schema_first.empty_blocks", task_id=str(input.task_id))
            agent_metrics.record_node_execution(self._config.role, "schema_first:empty_blocks")
            return await self._run_legacy(input, task_input)

        document = align_formatter_meta(document, task_input)
        agent_metrics.record_node_execution(self._config.role, "schema_first:success")
        logger.info(
            "formatter.llm_path",
            formatter_mode="schema_first",
            task_id=str(input.task_id),
            max_tokens=max_tokens,
            final_text_chars=len(str(user_payload.get("final_text") or "")),
            user_payload_chars=len(user_message),
            style_hint=user_payload.get("style_hint"),
            **formatter_attachment_stats(task_input, user_payload),
        )
        status: Literal["success", "partial"] = "partial" if task_input.requires_review else "success"
        return AgentOutput(
            task_id=input.task_id,
            status=status,
            confidence=document.meta.confidence,
            output=document,
        )

    async def _run_legacy(self, input: AgentInput, task_input: FormatterInput) -> AgentOutput:
        """GFM Markdown stream → parse → align meta → optional locale repair."""
        user_payload = build_formatter_user_payload(task_input)
        user_message = build_formatter_user_message(user_payload)
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=FORMATTER_SYSTEM_PROMPT),
            ChatMessage(role="user", content=user_message),
        ]
        style_hint = user_payload.get("style_hint")
        final_text_len = len(str(user_payload.get("final_text") or ""))
        max_tokens = formatter_max_tokens(
            user_message,
            style_hint=str(style_hint) if isinstance(style_hint, str) else None,
            final_text_len=final_text_len,
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
        except PARSE_ERRORS as parse_exc:
            # Repair exhausted. Worker draft may still render deterministically.
            # Prefer graceful degradation over empty document + review flag.
            logger.warning(
                "formatter.parse_errors_falling_back_to_deterministic",
                task_id=str(input.task_id),
                error=str(parse_exc)[:300],
            )
            agent_metrics.record_node_execution(self._config.role, "emit:fallback_after_parse_errors")
            return failure_or_fallback(
                input=input,
                task_input=task_input,
                user_payload=user_payload,
                max_tokens=max_tokens,
                agent_role=self._config.role,
            )
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
            **formatter_attachment_stats(task_input, user_payload),
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
