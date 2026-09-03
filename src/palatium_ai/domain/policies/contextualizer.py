# src/palatium_ai/domain/policies/contextualizer.py

"""When Contextualizer must call an LLM vs pass-through.

Primary graph order: Contextualizer → Intent. Without task_kind yet, any turn with
assistant prior invokes rewrite so Intent receives live continuation_kind hints.

When task_kind is already known (tests / optional re-entry), social and capability
asks skip the LLM: they are self-contained; Continuity still sees dialog.

Does not inspect user phrasing.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.types import TaskKind


class ContextualizerGateDecision(BaseModel):
    """Outcome of ContextualizerPolicy for one turn."""

    model_config = {"frozen": True}

    invoke_llm: bool
    reason: str = Field(min_length=1, max_length=128)


class ContextualizerPolicy:
    """Pure domain policy: prior + task_kind → Contextualizer LLM or pass-through."""

    _PRIOR_DEPENDENT_KINDS: frozenset[str] = frozenset(
        {
            "knowledge_request",
            "multi_step_workflow",
            "tool_execution",
            "response_formatting",
            "clarification_needed",
        }
    )

    @classmethod
    def decide(
        cls,
        *,
        has_assistant_prior: bool,
        task_kind: TaskKind | None,
        requires_mcp: bool,
    ) -> ContextualizerGateDecision:
        """Return whether Contextualizer must call an LLM."""
        if not has_assistant_prior:
            return ContextualizerGateDecision(invoke_llm=False, reason="no_assistant_prior")

        if requires_mcp:
            return ContextualizerGateDecision(invoke_llm=True, reason="mcp_may_need_prior")

        if task_kind is None:
            return ContextualizerGateDecision(invoke_llm=True, reason="unknown_task_kind")

        if task_kind in cls._PRIOR_DEPENDENT_KINDS:
            return ContextualizerGateDecision(invoke_llm=True, reason=f"prior_dependent:{task_kind}")

        return ContextualizerGateDecision(invoke_llm=False, reason=f"self_contained:{task_kind}")
