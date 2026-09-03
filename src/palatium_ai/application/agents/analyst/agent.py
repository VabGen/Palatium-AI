# src/palatium_ai/application/agents/analyst/agent.py

"""Analyst — BaseAgent structured analysis (030)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING, Literal

from palatium_ai.application.agents.analyst.parsing import decode_analyst_input, parse_analyst_output
from palatium_ai.application.agents.analyst.prompts import ANALYST_SYSTEM_PROMPT
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.analyst import AnalystOutput
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.llm.models import ChatMessage

if TYPE_CHECKING:
    from palatium_ai.domain.agents.agent_config import AgentConfig

logger = get_logger(__name__)


class AnalystAgent(BaseAgent):
    """Produces analysis drafts from context; no code execution."""

    @property
    def config(self) -> AgentConfig:
        return self._config

    def get_required_context_keys(self) -> list[str]:
        return ["context_packet_json", "revision_feedback"]

    def get_available_tools(self) -> list[str]:
        return list(self._config.allowed_tools)

    @traceable(name="analyst.run")
    async def run(self, input: AgentInput) -> AgentOutput:
        agent_metrics.record_node_execution(self._config.role, "run")
        task_input = decode_analyst_input({**input.context, "_task_id": str(input.task_id)})
        user_payload = {
            "user_text": task_input.context_packet.user_text,
            "route_plan": task_input.context_packet.route_plan,
            "context_summary": task_input.context_packet.context_summary,
            "revision_feedback": task_input.revision_feedback or "",
        }
        try:
            completion = await self._harness.call_llm(
                self._config,
                [
                    ChatMessage(role="system", content=ANALYST_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
                ],
                response_format="json_object",
            )
            output = parse_analyst_output(completion.content)
        except Exception:
            logger.exception("analyst LLM stage failed", task_id=str(input.task_id))
            agent_metrics.record_error(self._config.role, "llm_stage_failure")
            return AgentOutput(
                task_id=input.task_id,
                status="failure",
                confidence=0.0,
                output=AnalystOutput(summary="failure", confidence=0.0),
                error_message="LLM stage failed in analyst agent",
            )

        status: Literal["success", "failure", "partial"] = (
            "partial" if output.confidence < self._config.confidence_threshold else "success"
        )
        return AgentOutput(
            task_id=input.task_id,
            status=status,
            confidence=output.confidence,
            output=output,
        )
