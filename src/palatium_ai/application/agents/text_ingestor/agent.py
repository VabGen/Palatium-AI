# src/palatium_ai/application/agents/text_ingestor/agent.py

"""TextIngestor — нормализация, чанкинг и optional contextual prefix (off hot path)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from palatium_ai.application.agents.text_ingestor.chunking import (
    chunk_text,
    compute_chunking_confidence,
    normalize_text,
)
from palatium_ai.application.agents.text_ingestor.config import MAX_CHUNKS_FOR_CONTEXT_PREFIX
from palatium_ai.application.agents.text_ingestor.parsing import (
    apply_context_prefixes,
    decode_text_ingestor_input,
    parse_context_prefixes,
)
from palatium_ai.application.agents.text_ingestor.prompts import (
    TEXT_INGESTOR_CONTEXT_PREFIX_SYSTEM_PROMPT,
    build_context_prefix_user_prompt,
)
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.agents.text_ingestor import TextIngestorOutput
from palatium_ai.domain.llm.models import ChatMessage

if TYPE_CHECKING:
    from palatium_ai.domain.agents.agent_config import AgentConfig

logger = get_logger(__name__)

CONTEXT_PREFIX_STAGE_FAILURE = "text_ingestor_context_prefix_stage_failure"


class TextIngestorAgent(BaseAgent):
    """Готовит чанки для ingest_document; write через MCP — отдельный HITL-шаг (020)."""

    @property
    def config(self) -> AgentConfig:
        return self._config

    def get_required_context_keys(self) -> list[str]:
        return ["task_id", "thread_id", "raw_text", "enrich_context_prefix"]

    def get_available_tools(self) -> list[str]:
        return list(self._config.allowed_tools)

    @traceable(name="text_ingestor.run")
    async def run(self, input: AgentInput) -> AgentOutput:
        agent_metrics.record_node_execution(self._config.role, "run")
        try:
            task_input = decode_text_ingestor_input(input.context)
        except ValueError as exc:
            logger.warning("text_ingestor invalid input", error=str(exc), task_id=str(input.task_id))
            return AgentOutput(
                task_id=input.task_id,
                status="failure",
                confidence=0.0,
                output=TextIngestorOutput(normalized_char_count=0),
                error_message=str(exc),
            )

        normalized = normalize_text(task_input.raw_text)
        strategy, chunks = chunk_text(normalized, max_chars=task_input.max_chunk_chars)
        confidence = compute_chunking_confidence(chunks, max_chars=task_input.max_chunk_chars)
        prefixes_applied = False
        prefix_error: str | None = None

        if task_input.enrich_context_prefix and chunks:
            limited = chunks[:MAX_CHUNKS_FOR_CONTEXT_PREFIX]
            try:
                completion = await self._harness.call_llm(
                    self._config,
                    [
                        ChatMessage(role="system", content=TEXT_INGESTOR_CONTEXT_PREFIX_SYSTEM_PROMPT),
                        ChatMessage(
                            role="user",
                            content=build_context_prefix_user_prompt(
                                document_title=task_input.document_title,
                                chunks=limited,
                            ),
                        ),
                    ],
                    response_format="json_object",
                )
                prefixes = parse_context_prefixes(completion.content, expected=len(limited))
                enriched = apply_context_prefixes(limited, prefixes)
                chunks = enriched + chunks[len(limited) :] if len(chunks) > len(limited) else enriched
                prefixes_applied = True
                covered = sum(1 for chunk in enriched if chunk.contextual_prefix.strip())
                prefix_ratio = covered / len(enriched) if enriched else 0.0
                confidence = min(confidence, 0.5 + 0.5 * prefix_ratio)
            except Exception:
                logger.exception(
                    "text_ingestor context prefix stage failed",
                    thread_id=task_input.thread_id,
                    task_id=str(input.task_id),
                )
                agent_metrics.record_error(self._config.role, "context_prefix_stage_failure")
                prefix_error = CONTEXT_PREFIX_STAGE_FAILURE

        output = TextIngestorOutput(
            chunks=chunks,
            chunking_strategy=strategy,
            normalized_char_count=len(normalized),
            context_prefixes_applied=prefixes_applied,
        )

        status: Literal["success", "failure", "partial"]
        if not chunks:
            status = "failure"
            error_message = "no chunks produced after normalization"
        elif prefix_error is not None:
            status = "partial"
            error_message = prefix_error
        elif confidence < self._config.confidence_threshold:
            status = "partial"
            error_message = "chunk quality below confidence threshold"
        else:
            status = "success"
            error_message = None

        return AgentOutput(
            task_id=input.task_id,
            status=status,
            confidence=confidence,
            output=output,
            error_message=error_message,
        )
