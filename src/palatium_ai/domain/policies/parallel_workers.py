# src/palatium_ai/domain/policies/parallel_workers.py

"""When Researcher and Analyst may run in parallel (latency P2.15, 055).

Pure policy: multi-capability turns that need both knowledge retrieval and
structured analysis fan out; single-capability stays sequential (one worker).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.agents.execution import ANALYST_STRATEGIES, RESEARCHER_STRATEGIES
from palatium_ai.domain.mcp.models import ToolExecutionPlan

_RESEARCH_CAPS: frozenset[str] = frozenset({"search", "knowledge", "retrieve", "rag", "docs", "documents"})
_ANALYST_CAPS: frozenset[str] = frozenset({"analytics", "analysis", "metrics", "trends", "stats", "statistics"})


class ParallelWorkersDecision(BaseModel):
    """Outcome of ParallelWorkerPolicy for one turn."""

    model_config = {"frozen": True}

    parallel: bool
    reason: str = Field(min_length=1, max_length=128)


class ParallelWorkerPolicy:
    """Decide multi-step research∥analyst fan-out from capabilities / plan steps."""

    @classmethod
    def decide_from_capabilities(
        cls, *, candidate_capabilities: tuple[str, ...] | list[str]
    ) -> ParallelWorkersDecision:
        """Whether planner should emit both retrieve and data_analysis steps."""
        caps = {c.strip().lower() for c in candidate_capabilities if c and c.strip()}
        has_research = bool(caps & _RESEARCH_CAPS)
        has_analyst = bool(caps & _ANALYST_CAPS)
        if has_research and has_analyst:
            return ParallelWorkersDecision(parallel=True, reason="research_and_analytics_caps")
        return ParallelWorkersDecision(parallel=False, reason="single_capability_path")

    @classmethod
    def decide_from_steps(
        cls, steps: tuple[ToolExecutionPlan, ...] | list[ToolExecutionPlan]
    ) -> ParallelWorkersDecision:
        """Whether graph should route to the parallel workers node."""
        strategies = {step.strategy for step in steps}
        has_research = bool(strategies & RESEARCHER_STRATEGIES)
        has_analyst = bool(strategies & ANALYST_STRATEGIES)
        if has_research and has_analyst and len(steps) >= 2:
            return ParallelWorkersDecision(parallel=True, reason="multi_step_research_analyst")
        return ParallelWorkersDecision(parallel=False, reason="sequential_worker")
