# src/palatium_ai/application/agents/critic/agent.py

"""Critic — BaseAgent implementation (030)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING, Literal

from palatium_ai.application.agents.critic.config import (
    ACCURACY_REVIEW_THRESHOLD,
    PASSTHROUGH_ACCURACY,
    PASSTHROUGH_SAFETY,
    SAFETY_REVIEW_THRESHOLD,
)
from palatium_ai.application.agents.critic.parsing import (
    confidence_from_scores,
    decode_critic_input,
    parse_critic_output,
)
from palatium_ai.application.agents.critic.prompts import CRITIC_SYSTEM_PROMPT
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.critic import CriticOutput
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.domain.policies import CriticPolicy

if TYPE_CHECKING:
    from palatium_ai.domain.agents.agent_config import AgentConfig

logger = get_logger(__name__)


class CriticAgent(BaseAgent):
    """Проверяет качество platform classification/route/worker draft."""

    @property
    def config(self) -> AgentConfig:
        return self._config

    def get_required_context_keys(self) -> list[str]:
        return [
            "context_packet_json",
            "classification_confidence",
            "classification_reasoning",
            "worker_summary",
            "selected_strategy",
            "continuation_kind",
            "user_input_chars",
        ]

    def get_available_tools(self) -> list[str]:
        return []

    @traceable(name="critic.run")
    async def run(self, input: AgentInput) -> AgentOutput:
        agent_metrics.record_node_execution(self._config.role, "run")
        task_input = decode_critic_input({**input.context, "_task_id": str(input.task_id)})

        gate = CriticPolicy.decide(
            selected_strategy=task_input.selected_strategy,
            task_kind=task_input.context_packet.task_kind,
            continuation_kind=task_input.continuation_kind,
            classification_confidence=task_input.classification_confidence,
            confidence_threshold=self._config.confidence_threshold,
            requires_mcp=task_input.context_packet.requires_mcp,
            requires_tool_call=task_input.context_packet.execution_plan.requires_tool_call,
            worker_summary=task_input.worker_summary,
            user_input_chars=task_input.user_input_chars,
        )
        if not gate.invoke_llm:
            agent_metrics.record_node_execution(self._config.role, f"passthrough:{gate.reason}")
            output = CriticOutput(
                accuracy_score=PASSTHROUGH_ACCURACY,
                safety_score=PASSTHROUGH_SAFETY,
                requires_review=False,
                summary=f"CriticPolicy passthrough ({gate.reason}).",
            )
            return AgentOutput(
                task_id=input.task_id,
                status="success",
                confidence=confidence_from_scores(output),
                output=output,
            )

        messages = [
            ChatMessage(role="system", content=CRITIC_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=json.dumps(
                    {
                        "user_text": task_input.context_packet.user_text,
                        "task_kind": task_input.context_packet.task_kind,
                        "route": task_input.context_packet.route,
                        "selected_strategy": task_input.selected_strategy,
                        "continuation_kind": task_input.continuation_kind,
                        "context_summary": task_input.context_packet.context_summary,
                        "classification_confidence": task_input.classification_confidence,
                        "classification_reasoning": task_input.classification_reasoning,
                        "route_plan": task_input.context_packet.route_plan,
                        "worker_summary": task_input.worker_summary,
                    },
                    ensure_ascii=False,
                ),
            ),
        ]

        try:
            completion = await self._harness.call_llm(
                self._config,
                messages,
                response_format="json_object",
            )
            output = parse_critic_output(completion.content)
        except Exception:
            logger.exception("critic LLM stage failed", task_id=str(input.task_id))
            agent_metrics.record_error(self._config.role, "llm_stage_failure")
            return AgentOutput(
                task_id=input.task_id,
                status="failure",
                confidence=0.0,
                output=_empty_critic_output(),
                error_message="LLM stage failed in critic agent",
            )

        requires_review = (
            output.requires_review
            or output.accuracy_score < ACCURACY_REVIEW_THRESHOLD
            or output.safety_score < SAFETY_REVIEW_THRESHOLD
        )
        status: Literal["success", "failure", "partial"] = "partial" if requires_review else "success"
        if requires_review:
            agent_metrics.record_human_escalation("critic_requires_review")

        return AgentOutput(
            task_id=input.task_id,
            status=status,
            confidence=confidence_from_scores(output),
            output=output,
        )


def _empty_critic_output() -> CriticOutput:
    return CriticOutput(
        accuracy_score=0,
        safety_score=0,
        requires_review=True,
        summary="failure",
    )
