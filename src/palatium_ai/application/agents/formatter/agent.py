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

from palatium_ai.application.agents.formatter.answer_delta import (
    emit_document_block,
    emit_document_title,
    emit_structured_answer_delta,
)
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
from palatium_ai.application.agents.formatter.partial_document import PartialDocumentScanner
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
from palatium_ai.domain.attachments.citations import attachment_ids_by_label
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.content.citations import CitationRef, normalize_citations
from palatium_ai.domain.content.lint import ContentLint
from palatium_ai.domain.llm.errors import StructuredOutputUnsupportedError
from palatium_ai.domain.llm.models import ChatMessage, LLMCompletion
from palatium_ai.domain.policies.locale import ReplyLocalePolicy
from palatium_ai.domain.policies.shape import ShapeRecipePolicy

if TYPE_CHECKING:
    from uuid import UUID

    from palatium_ai.application.agents.formatter.partial_document import PartialFrame
    from palatium_ai.domain.agents.agent_config import AgentConfig
    from palatium_ai.domain.agents.formatter import FormatterInput
    from palatium_ai.domain.ports.harness import HarnessPort

logger = get_logger(__name__)

# Re-exports for unit tests that import / monkeypatch helpers via this module.
_first_token_fallback_watch = first_token_fallback_watch
_repair_max_tokens = repair_max_tokens
_FIRST_TOKEN_FALLBACK_SECONDS = FIRST_TOKEN_FALLBACK_SECONDS


def _paint_partial_frames(frames: list[PartialFrame], *, painted_prose: bool) -> bool:
    """Paint one batch of closed document frames; return the prose-painted flag.

    Typed frame first: the client prefers it and renders the same ``BlockRenderer``
    as the final document. Prose is the append-only fallback for clients that predate
    the typed frames (dual-emit, like ``text_delta``/``answer_delta`` in Phase 1).
    The document title is not a block, so it gets its own typed frame before the
    blocks: painting it as prose first would move the text when blocks take over.
    """
    for frame in frames:
        if frame.index < 0:
            emit_document_title(frame.text)
        elif frame.block is not None:
            emit_document_block(index=frame.index, block=frame.block)
        if frame.text:
            if frame.continues_prose:
                # Same paragraph, next delta: no break, no whitespace trimming —
                # a stripped boundary would glue words together on screen.
                emit_structured_answer_delta(frame.text, separator="", keep_whitespace=True)
            else:
                emit_structured_answer_delta(frame.text, separator="\n\n" if painted_prose else "")
            painted_prose = True
    return painted_prose


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
            output = (
                await self._run_schema_first(input, task_input)
                if effective_mode == "schema_first"
                else await self._run_legacy(input, task_input)
            )
        finally:
            # Mode-split latency for the canary A/B: both cohorts share one process, so
            # comparing schema_first against the legacy baseline needs this label.
            agent_metrics.record_node_execution(
                self._config.role,
                f"formatter:{effective_mode}",
                duration_seconds=perf_counter() - started,
            )
        self._record_shape_verdict(task_input, output)
        self._record_content_lint(task_input, output)
        return output

    def _record_content_lint(self, task_input: FormatterInput, output: AgentOutput) -> None:
        """Measure deterministic defects that are schema-valid but wrong for the user.

        Findings never change the answer: content repair stays in the formatter
        pipeline, so the lint cannot become a second author of the document (050).
        Prose is not logged — only rule ids, severity counts and the task id (020).
        """
        document = output.output
        if not isinstance(document, ContentDocument):
            return
        report = ContentLint.run(document)
        if not report.findings:
            return
        for finding in report.findings:
            agent_metrics.record_content_lint_finding(rule=finding.rule_id, severity=finding.severity)
        logger.warning(
            "formatter.content_lint.findings",
            task_id=str(task_input.task_id),
            error_count=report.error_count,
            warning_count=len(report.findings) - report.error_count,
            rules=sorted({finding.rule_id for finding in report.findings}),
        )

    def _resolve_citations(
        self,
        completion: LLMCompletion,
        *,
        task_id: UUID,
        untrusted_context: str = "",
    ) -> tuple[CitationRef, ...]:
        """Resolve provider citations against the text they annotate (W3a) and keep them (W3b).

        The answer text is never changed here. ``answer_range`` is validated in its own
        coordinate space — the raw provider output — because an offset that is meaningful
        in the answer text is meaningless in a reformatted document. Resolved anchors are
        attached to ``meta.citations`` by the caller, so the UI can show what the model
        actually cited instead of a filename chip inferred from the prose.

        ``source_id`` is bound here from the turn's fence headers (W3b-2): the label the
        model cites is a display name, and only the fence knows which upload produced it.
        An ambiguous label stays unbound — the UI then offers no "show in source" action
        rather than opening a same-named file that may belong to someone else (020).
        """
        if not completion.citations:
            return ()
        report = normalize_citations(completion.citations, answer_text=completion.content)
        for anchor, outcome in report.outcomes:
            agent_metrics.record_citation_resolution(anchor=anchor, outcome=outcome)
        if report.out_of_range or report.unanchored:
            logger.warning(
                "formatter.citations.dropped",
                task_id=str(task_id),
                emitted=report.emitted,
                resolved=len(report.resolved),
                out_of_range=report.out_of_range,
                unanchored=report.unanchored,
            )
        return _bind_source_ids(report.resolved, untrusted_context)

    def _record_shape_verdict(self, task_input: FormatterInput, output: AgentOutput) -> None:
        """Measure whether an explicitly requested form matched the document.

        Never changes the answer: Pydantic already guarantees a valid document, and the
        content is correct even when the composition differs (ADR 0005). A repair pass
        is deliberately absent: the streamed blocks are already painted, so rewriting
        the document afterwards would replace what the user reads (040 layout shift) —
        the exact invariant this wave establishes. Mismatch stays a metric.
        """
        recipe = ShapeRecipePolicy.resolve(
            shape=task_input.context_packet.response_shape,
            task_kind=task_input.context_packet.task_kind,
        )
        if recipe is None:
            return
        document = output.output
        if not isinstance(document, ContentDocument):
            return
        verdict = ShapeRecipePolicy.validate(document, recipe)
        agent_metrics.record_response_shape(
            shape=verdict.shape,
            outcome="satisfied" if verdict.satisfied else "mismatch",
        )
        if not verdict.satisfied:
            logger.info(
                "formatter.response_shape.mismatch",
                task_id=str(task_input.task_id),
                shape=verdict.shape,
                reason=verdict.reason,
            )

    async def _run_schema_first(self, input: AgentInput, task_input: FormatterInput) -> AgentOutput:
        """Provider-enforced ContentDocument json_schema; legacy Markdown is the fallback.

        Streamed, not buffered: the provider emits the JSON incrementally and every
        block that closes is painted immediately (``structured_incremental``). The
        final validated document is a superset of the painted prose, so it never
        replaces it — that is the difference between this contract and a blocking
        ``json_schema`` call followed by a full-document swap (055).
        """
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
        scanner = PartialDocumentScanner()
        painted_prose = False

        def _on_delta(chunk: str) -> None:
            nonlocal painted_prose
            painted_prose = _paint_partial_frames(scanner.feed(chunk), painted_prose=painted_prose)

        try:
            completion = await self._harness.call_llm_stream(
                self._config,
                messages,
                response_format="json_schema",
                response_model=ContentDocument,
                max_tokens=max_tokens,
                on_delta=_on_delta,
            )
            _paint_partial_frames(scanner.pending(), painted_prose=painted_prose)
            citations = self._resolve_citations(
                completion,
                task_id=input.task_id,
                untrusted_context=task_input.context_packet.untrusted_context,
            )
            document = ContentDocument.model_validate_json(completion.content)
        except StructuredOutputUnsupportedError:
            logger.warning("formatter.schema_first.unsupported", task_id=str(input.task_id))
            agent_metrics.record_formatter_schema(path="schema_first", outcome="unsupported")
            return await self._run_legacy(input, task_input)
        except ValidationError as exc:
            logger.warning(
                "formatter.schema_first.invalid_json",
                task_id=str(input.task_id),
                error=str(exc)[:300],
            )
            agent_metrics.record_formatter_schema(path="schema_first", outcome="invalid")
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
            agent_metrics.record_formatter_schema(path="schema_first", outcome="empty_blocks")
            return await self._run_legacy(input, task_input)

        document = align_formatter_meta(document, task_input)
        if citations:
            # Attached after validation, never emitted by the model: blocks are already
            # painted, and meta does not change layout (W1 invariant).
            document = document.model_copy(update={"meta": document.meta.model_copy(update={"citations": citations})})
        agent_metrics.record_formatter_schema(path="schema_first", outcome="valid")
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
                allow_worker_fallback=task_input.allow_worker_fallback,
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
            agent_metrics.record_formatter_schema(path="legacy_markdown", outcome="fallback")
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
        agent_metrics.record_formatter_schema(path="legacy_markdown", outcome="valid")
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


def _bind_source_ids(citations: tuple[CitationRef, ...], untrusted_context: str) -> tuple[CitationRef, ...]:
    """Attach ``source_id`` where the fence headers name exactly one upload.

    The mapping is built by the same rule that builds the visible chips, so a chip
    always opens the file it names; a label that stays ambiguous is left unbound.
    """
    by_label = attachment_ids_by_label(untrusted_context)
    if not by_label:
        return citations
    bound: list[CitationRef] = []
    for citation in citations:
        attachment_id = by_label.get(citation.source_ref)
        bound.append(citation if attachment_id is None else citation.model_copy(update={"source_id": attachment_id}))
    return tuple(bound)
