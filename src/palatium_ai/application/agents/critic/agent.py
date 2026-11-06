# src/palatium_ai/application/agents/critic/agent.py

"""Critic — BaseAgent implementation (030)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING, Literal

from pydantic import ValidationError

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
from palatium_ai.domain.llm.json_codec import LLMJSONError
from palatium_ai.domain.llm.response_parser import compact_validation_error, parse_llm_response
from palatium_ai.domain.policies import CriticPolicy
from palatium_ai.domain.policies.constitution import Constitution, ConstitutionViolation, PrincipleId
from palatium_ai.domain.policies.hop_budget import HopBudgetPolicy
from palatium_ai.domain.policies.prompt_assembly import PromptAssemblyParts, PromptAssemblyPolicy
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
            "memory_hints_json",
        ]

    def get_available_tools(self) -> list[str]:
        return []

    @traceable(name="critic.run")
    async def run(self, input: AgentInput) -> AgentOutput:
        agent_metrics.record_node_execution(self._config.role, "run")
        task_input = decode_critic_input({**input.context, "_task_id": str(input.task_id)})
        # Deterministic constitution pass runs before any judge decision: a skipped
        # judge (budget/policy) must not become a skipped safety check (020).
        # memory_hints are first-class turn inputs for PII permission (060): a name the
        # user stated earlier is allowed evidence, not an invented leak (055).
        allowed_sources = (
            task_input.context_packet.user_text,
            task_input.context_packet.untrusted_context or "",
            *task_input.memory_hints,
        )
        deterministic = Constitution.check(
            draft=task_input.worker_summary,
            sources=allowed_sources,
        )

        hop = get_hop_collector()
        if hop is not None:
            budget_gate = HopBudgetPolicy.should_skip_critic_llm(
                hop_total_ms=hop.agent_ms(),
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

        memory_block = "\n".join(f"- {hint}" for hint in task_input.memory_hints if str(hint).strip())
        assembled = PromptAssemblyPolicy.assemble(
            PromptAssemblyParts(
                system_identity=CRITIC_SYSTEM_PROMPT,
                memory_block=memory_block,
                user_content=json.dumps(
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
                        "memory_hints": list(task_input.memory_hints),
                        "classification_confidence": task_input.classification_confidence,
                        "classification_reasoning": task_input.classification_reasoning,
                        "route_plan": task_input.context_packet.route_plan,
                        "worker_summary": task_input.worker_summary,
                    },
                    ensure_ascii=False,
                ),
            )
        )
        messages = list(assembled.messages)

        try:
            # Provider structured output: the harness builds the json_schema payload
            # from the model. The decoder still strips fences/prose and repairs minor
            # JSON defects — providers return them even under a strict schema (055).
            completion = await self._harness.call_llm(
                self._config,
                messages,
                response_format="json_schema",
                response_model=CriticOutput,
            )
            output = parse_llm_response(completion.content, CriticOutput)
        except (ValidationError, LLMJSONError) as exc:
            # Model-side defect: worth a distinct series, and no traceback — this is a
            # prompt/provider signal, not an unexpected crash (040).
            logger.warning(
                "critic.structured_output_invalid",
                task_id=str(input.task_id),
                error=compact_validation_error(exc),
            )
            agent_metrics.record_error(self._config.role, "structured_output_invalid")
            return AgentOutput(
                task_id=input.task_id,
                status="failure",
                confidence=0.0,
                output=_empty_critic_output(),
                error_message="LLM stage failed in critic agent",
            )
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


#: Pattern-scanned articles (constitution docstring): the scanner is SoT. A judge that
#: invents ``no_pii_echo_without_permission`` for a first-name recall must not escalate
#: when the deterministic pass is clean (055 — live "как меня зовут?" / quality_review).
_SCANNER_OWNED_PRINCIPLES: frozenset[PrincipleId] = frozenset({"no_pii_echo_without_permission"})


def _merge_constitution(
    output: CriticOutput,
    deterministic: tuple[ConstitutionViolation, ...],
) -> CriticOutput:
    """Union of judged and deterministic article ids, order-stable, no duplicates.

    Scanner-owned principles stay only when the deterministic pass found them: the
    judge may not invent a PII leak for classes the scanner does not cover (names).
    """
    deterministic_ids = {item.principle for item in deterministic}
    judged = tuple(
        principle
        for principle in output.violations
        if principle not in _SCANNER_OWNED_PRINCIPLES or principle in deterministic_ids
    )
    merged_violations = tuple(dict.fromkeys((*judged, *deterministic_ids)))
    updates: dict[str, object] = {}
    if merged_violations != output.violations:
        updates["violations"] = merged_violations
    dropped_false_pii = any(principle in _SCANNER_OWNED_PRINCIPLES for principle in output.violations) and not any(
        principle in _SCANNER_OWNED_PRINCIPLES for principle in merged_violations
    )
    # Drop the review bit / depressed safety the judge tied solely to the invented PII
    # hit; remaining accuracy/safety thresholds in ``_finalize`` still apply for
    # unrelated low scores.
    if dropped_false_pii and not merged_violations:
        if output.requires_review:
            updates["requires_review"] = False
        if output.safety_score < SAFETY_REVIEW_THRESHOLD:
            updates["safety_score"] = SAFETY_REVIEW_THRESHOLD
    if not updates:
        return output
    return output.model_copy(update=updates)


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
