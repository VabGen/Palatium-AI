# src/palatium_ai/application/agents/memory_keeper/agent.py

"""MemoryKeeper — BaseAgent implementation (030)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from palatium_ai.application.agents.memory_keeper.config import MAX_EXISTING_MEMORIES
from palatium_ai.application.agents.memory_keeper.parsing import (
    decode_memory_keeper_input,
    parse_memory_keeper_output,
)
from palatium_ai.application.agents.memory_keeper.prompts import MEMORY_KEEPER_SYSTEM_PROMPT
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.memory_keeper import MemoryKeeperOutput
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.llm.models import ChatMessage

if TYPE_CHECKING:
    from palatium_ai.domain.agents.agent_config import AgentConfig

logger = get_logger(__name__)

LLM_STAGE_FAILURE = "memory_keeper_llm_stage_failure"


class MemoryKeeperAgent(BaseAgent):
    """Consolidates transcript into ADD-only memory candidates (sleep-time, off hot path)."""

    @property
    def config(self) -> AgentConfig:
        return self._config

    def get_required_context_keys(self) -> list[str]:
        return [
            "thread_id",
            "transcript_excerpt",
            "existing_memory_texts_json",
        ]

    def get_available_tools(self) -> list[str]:
        return []

    @traceable(name="memory_keeper.run")
    async def run(self, input: AgentInput) -> AgentOutput:
        agent_metrics.record_node_execution(self._config.role, "run")
        task_input = decode_memory_keeper_input(input.context)

        existing = (
            "\n".join(f"- {text}" for text in task_input.existing_memory_texts[:MAX_EXISTING_MEMORIES]) or "(none)"
        )
        user_prompt = (
            f"thread_id={task_input.thread_id}\n"
            f"existing_memories:\n{existing}\n\n"
            "<<<UNTRUSTED_TRANSCRIPT>>>\n"
            f"{task_input.transcript_excerpt}\n"
            "<<<END_UNTRUSTED_TRANSCRIPT>>>"
        )

        try:
            completion = await self._harness.call_llm(
                self._config,
                [
                    ChatMessage(role="system", content=MEMORY_KEEPER_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=user_prompt),
                ],
                response_format="json_object",
            )
            output = parse_memory_keeper_output(completion.content)
        except Exception:
            logger.exception(
                "memory_keeper LLM stage failed",
                thread_id=task_input.thread_id,
                task_id=str(input.task_id),
            )
            agent_metrics.record_error(self._config.role, "llm_stage_failure")
            return AgentOutput(
                task_id=input.task_id,
                status="success",
                confidence=1.0,
                output=MemoryKeeperOutput(facts=(), reasoning="skipped: llm stage failed"),
                error_message=LLM_STAGE_FAILURE,
            )

        high = tuple(f for f in output.facts if f.confidence >= self._config.confidence_threshold)

        if high:
            confidence = min(f.confidence for f in high)
            status: Literal["success", "failure", "partial"] = (
                "success" if len(high) == len(output.facts) else "partial"
            )
        elif output.facts:
            confidence = max(f.confidence for f in output.facts)
            status = "partial"
        else:
            confidence = 1.0
            status = "success"

        if not high and output.facts:
            logger.info(
                "memory_keeper: all facts below threshold",
                fact_count=len(output.facts),
                task_id=str(input.task_id),
            )

        return AgentOutput(
            task_id=input.task_id,
            status=status,
            confidence=confidence,
            output=MemoryKeeperOutput(facts=high, reasoning=output.reasoning),
        )
