# src/palatium_ai/application/agents/intent_classifier/agent.py

"""IntentClassifier — BaseAgent implementation (030)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING

from palatium_ai.application.agents.intent_classifier.parsing import parse_classifier_output
from palatium_ai.application.agents.intent_classifier.prompts import INTENT_CLASSIFIER_SYSTEM_PROMPT
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.llm.models import ChatMessage

if TYPE_CHECKING:
    from palatium_ai.domain.agents.agent_config import AgentConfig


class IntentClassifierAgent(BaseAgent):
    """Classifies user intent. LLM only via Harness."""

    @property
    def config(self) -> AgentConfig:
        return self._config

    def get_required_context_keys(self) -> list[str]:
        return ["continuation_kind", "has_prior_dialog"]

    def get_available_tools(self) -> list[str]:
        return []

    @traceable(name="intent_classifier.run")
    async def run(self, input: AgentInput) -> AgentOutput:
        agent_metrics.record_node_execution(self._config.role, "run")
        continuation_kind = input.context.get("continuation_kind") or None
        has_prior_dialog = input.context.get("has_prior_dialog", "false").lower() == "true"
        messages = [
            ChatMessage(role="system", content=INTENT_CLASSIFIER_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=json.dumps(
                    {
                        "text": input.instruction,
                        "continuation_kind": continuation_kind,
                        "has_prior_dialog": has_prior_dialog,
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
            parsed = parse_classifier_output(completion.content)
        except Exception as exc:
            agent_metrics.record_error(self._config.role, type(exc).__name__)
            return AgentOutput(
                task_id=input.task_id,
                status="failure",
                confidence=0.0,
                output=_empty_intent_output(),
                error_message=str(exc),
            )

        return AgentOutput(
            task_id=input.task_id,
            status="success",
            confidence=parsed.confidence,
            output=parsed,
        )


def _empty_intent_output() -> IntentClassifierOutput:
    return IntentClassifierOutput(
        task_kind="clarification_needed",
        requires_mcp=False,
        requires_user_choice=False,
        underspecification_kind="none",
        candidate_capabilities=(),
        confidence=0.0,
        reasoning="failure",
    )
