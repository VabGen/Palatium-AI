# src/palatium_ai/application/orchestration/snapshot.py

"""Снимок orchestration state в виде удобного typed object."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from palatium_ai.application.orchestration import selectors
from palatium_ai.domain.agents.execution import ExecutionStrategy

if TYPE_CHECKING:
    from palatium_ai.application.orchestration.state import AgentGraphState
    from palatium_ai.domain.agents.context_packet import ContextPacket
    from palatium_ai.domain.agents.intent import IntentTaskResult, TaskKind
    from palatium_ai.domain.agents.supervisor import WorkerRoute


class OrchestrationSnapshot(BaseModel):
    """Нормализованное представление graph state для node-логики."""

    model_config = {"frozen": True}

    task_id: str
    user_text: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    classification: IntentTaskResult
    task_kind: TaskKind
    requires_mcp: bool
    candidate_capabilities: tuple[str, ...] = Field(default_factory=tuple)
    route: WorkerRoute
    route_plan: str = Field(min_length=1)
    classification_reasoning: str = Field(min_length=1)
    worker_summary: str | None = None
    critic_summary: str | None = None
    selected_strategy: ExecutionStrategy

    @classmethod
    def from_state(cls, state: AgentGraphState) -> OrchestrationSnapshot:
        """Собирает snapshot из сырого state."""
        classification = selectors.classification_result(state)
        return cls(
            task_id=classification.task_id,
            user_text=selectors.resolved_user_text(state),
            thread_id=selectors.resolved_thread_id(state),
            classification=classification,
            task_kind=selectors.resolved_task_kind(state),
            requires_mcp=selectors.resolved_requires_mcp(state),
            candidate_capabilities=selectors.resolved_candidate_capabilities(state),
            route=selectors.resolved_route(state),
            route_plan=selectors.resolved_route_plan(state),
            classification_reasoning=selectors.resolved_reasoning(state),
            worker_summary=selectors.resolved_worker_summary(state),
            critic_summary=selectors.resolved_critic_summary(state),
            selected_strategy=selectors.selected_strategy(state),
        )

    def context_packet(
        self,
        state: AgentGraphState,
        *,
        fallback_strategy: ExecutionStrategy,
        fallback_rationale: str,
    ) -> ContextPacket:
        """Возвращает ContextPacket для downstream node."""
        return selectors.resolved_context_packet(
            state,
            fallback_strategy=fallback_strategy,
            fallback_rationale=fallback_rationale,
        )


def _rebuild_snapshot_types() -> None:
    """Явно разрешает forward-ref типы для Pydantic v2."""
    from palatium_ai.application.orchestration.state import AgentGraphState as _AgentGraphState
    from palatium_ai.domain.agents.context_packet import ContextPacket as _ContextPacket
    from palatium_ai.domain.agents.execution import ExecutionStrategy as _ExecutionStrategy
    from palatium_ai.domain.agents.intent import (
        IntentTaskResult as _IntentTaskResult,
        TaskKind as _TaskKind,
    )
    from palatium_ai.domain.agents.supervisor import WorkerRoute as _WorkerRoute

    OrchestrationSnapshot.model_rebuild(
        _types_namespace={
            "AgentGraphState": _AgentGraphState,
            "ContextPacket": _ContextPacket,
            "ExecutionStrategy": _ExecutionStrategy,
            "IntentTaskResult": _IntentTaskResult,
            "TaskKind": _TaskKind,
            "WorkerRoute": _WorkerRoute,
        }
    )


_rebuild_snapshot_types()
