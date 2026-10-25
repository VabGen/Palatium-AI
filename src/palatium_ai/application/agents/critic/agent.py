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
)
from palatium_ai.application.agents.critic.prompts import CRITIC_SYSTEM_PROMPT
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.hop_timings import get_hop_collector
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.critic import CriticOutput
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.domain.policies import CriticPolicy
from palatium_ai.domain.policies.constitution import Constitution, ConstitutionViolation, PrincipleId
from palatium_ai.domain.policies.hop_budget import HopBudgetPolicy
from palatium_ai.domain.policies.types import VERBATIM_EXTRACTION_CAPABILITY

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
            "worker_confidence",
        ]

    def get_available_tools(self) -> list[str]:
        return []

    @traceable(name="critic.run")
    async def run(self, input: AgentInput) -> AgentOutput:
        agent_metrics.record_node_execution(self._config.role, "run")
        task_input = decode_critic_input({**input.context, "_task_id": str(input.task_id)})
        # Deterministic constitution pass runs before any judge decision: a skipped
        # judge (budget/policy) must not become a skipped safety check (020).
        deterministic = Constitution.check(
            draft=task_input.worker_summary,
            sources=(
                task_input.context_packet.user_text,
                task_input.context_packet.untrusted_context or "",
            ),
        )

        hop = get_hop_collector()
        if hop is not None:
            budget_gate = HopBudgetPolicy.should_skip_critic_llm(
                hop_total_ms=hop.total_ms(),
                budget_ms=hop.budget_ms,
            )
            if budget_gate.degrade:
                agent_metrics.record_node_execution(self._config.role, f"passthrough:{budget_gate.reason}")
                output = CriticOutput(
                    accuracy_score=PASSTHROUGH_ACCURACY,
                    safety_score=PASSTHROUGH_SAFETY,
                    requires_review=False,
                    summary=f"HopBudgetPolicy soft-degrade ({budget_gate.reason}).",
                )
                return self._finalize(input=input, output=output, deterministic=deterministic)

        caps = {cap.strip().lower() for cap in task_input.context_packet.candidate_capabilities}
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
            worker_confidence=task_input.worker_confidence,
            has_attachment_context=bool((task_input.context_packet.untrusted_context or "").strip()),
            verbatim_requested=VERBATIM_EXTRACTION_CAPABILITY in caps,
        )
        if not gate.invoke_llm:
            agent_metrics.record_node_execution(self._config.role, f"passthrough:{gate.reason}")
            output = CriticOutput(
                accuracy_score=PASSTHROUGH_ACCURACY,
                safety_score=PASSTHROUGH_SAFETY,
                requires_review=False,
                summary=f"CriticPolicy passthrough ({gate.reason}).",
            )
            return self._finalize(input=input, output=output, deterministic=deterministic)

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
                        "candidate_capabilities": list(task_input.context_packet.candidate_capabilities),
                        "context_summary": task_input.context_packet.context_summary,
                        # Neutral LLM-facing name (055): internal field names are
                        # echoed verbatim by the model into user prose.
                        "attached_files": task_input.context_packet.untrusted_context,
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
            # Provider structured output: the harness builds the json_schema payload
            # from the model, so the response is guaranteed to match CriticOutput.
            completion = await self._harness.call_llm(
                self._config,
                messages,
                response_format="json_schema",
                response_model=CriticOutput,
            )
            output = CriticOutput.model_validate_json(completion.content)
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

        if deterministic or output.violations:
            logger.info(
                "critic.constitution_checked",
                task_id=str(input.task_id),
                judged=list(output.violations),
                deterministic=[violation.principle for violation in deterministic],
            )
        return self._finalize(input=input, output=output, deterministic=deterministic)

    def _finalize(
        self,
        *,
        input: AgentInput,
        output: CriticOutput,
        deterministic: tuple[ConstitutionViolation, ...],
    ) -> AgentOutput:
        """Merge judged and deterministic article ids, then apply the review gate."""
        merged = _merge_constitution(output, deterministic)
        requires_review = (
            merged.requires_review
            or merged.accuracy_score < ACCURACY_REVIEW_THRESHOLD
            or merged.safety_score < SAFETY_REVIEW_THRESHOLD
            or bool(merged.violations)
        )
        _record_violations(merged.violations, deterministic)
        status: Literal["success", "failure", "partial"] = "partial" if requires_review else "success"
        if requires_review:
            agent_metrics.record_human_escalation("critic_requires_review")
        return AgentOutput(
            task_id=input.task_id,
            status=status,
            confidence=confidence_from_scores(merged),
            output=merged,
        )


def _empty_critic_output() -> CriticOutput:
    return CriticOutput(
        accuracy_score=0,
        safety_score=0,
        requires_review=True,
        summary="failure",
    )


def _merge_constitution(
    output: CriticOutput,
    deterministic: tuple[ConstitutionViolation, ...],
) -> CriticOutput:
    """Union of judged and deterministic article ids, order-stable, no duplicates."""
    if not deterministic:
        return output
    merged = tuple(dict.fromkeys((*output.violations, *(item.principle for item in deterministic))))
    return output.model_copy(update={"violations": merged})


def _record_violations(
    violations: tuple[PrincipleId, ...],
    deterministic: tuple[ConstitutionViolation, ...],
) -> None:
    """Count each violated article by origin; ``detail`` (detector ids) stays in logs."""
    deterministic_ids = {item.principle: item for item in deterministic}
    for principle in violations:
        found = deterministic_ids.get(principle)
        source = "deterministic" if found is not None else "judge"
        agent_metrics.record_constitution_violation(principle=principle, source=source)
        if found is not None:
            logger.warning(
                "critic.constitution_violation",
                principle=found.principle,
                severity=found.severity,
                detail=found.detail,
            )
