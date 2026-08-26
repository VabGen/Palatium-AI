# src/palatium_ai/application/services/context_packet_factory.py

"""Factory для сборки унифицированного ContextPacket."""

from __future__ import annotations

from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.execution import ExecutionStrategy
from palatium_ai.domain.agents.intent import IntentTaskResult, TaskKind
from palatium_ai.domain.agents.supervisor import SupervisorTaskResult
from palatium_ai.domain.mcp.models import ToolExecutionPlan


class ContextPacketFactory:
    """Строит ContextPacket из результатов upstream orchestration."""

    def from_state(
        self,
        *,
        task_id: str,
        user_text: str,
        classification: IntentTaskResult,
        routing: SupervisorTaskResult | None,
        fallback_strategy: ExecutionStrategy = "reason_only",
        fallback_rationale: str = "Fallback packet synthesized by graph.",
        effective_task_kind: TaskKind | None = None,
        effective_requires_mcp: bool | None = None,
        effective_capabilities: tuple[str, ...] | None = None,
    ) -> ContextPacket:
        """Собирает fallback packet, если ContextWeaver result недоступен."""
        raw_kind = classification.output.task_kind if classification.output is not None else "clarification_needed"
        raw_mcp = classification.output.requires_mcp if classification.output is not None else False
        raw_caps = classification.output.candidate_capabilities if classification.output is not None else tuple()
        task_kind = effective_task_kind if effective_task_kind is not None else raw_kind
        requires_mcp = effective_requires_mcp if effective_requires_mcp is not None else raw_mcp
        candidate_capabilities = effective_capabilities if effective_capabilities is not None else raw_caps
        route = routing.output.route if routing is not None and routing.output is not None else "clarification"
        route_plan = routing.output.plan if routing is not None and routing.output is not None else "No route plan"

        return ContextPacket(
            task_id=task_id,
            user_text=user_text,
            task_kind=task_kind,
            route=route,
            route_plan=route_plan,
            requires_mcp=requires_mcp,
            candidate_capabilities=candidate_capabilities,
            execution_plan=ToolExecutionPlan(
                strategy=fallback_strategy,
                requires_tool_call=False,
                rationale=fallback_rationale,
            ),
            context_summary=f"task_kind={task_kind}; route={route}; fallback_context_packet=true",
        )
