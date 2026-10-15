# src/palatium_ai/domain/policies/contextualizer.py

"""When Contextualizer must call an LLM vs pass-through.

Primary graph order (P0.1 latency): Intent → Contextualizer. Intent classifies the
raw turn first; Contextualizer receives ``task_kind`` and only rewrites when the
kind is prior-dependent (knowledge / tool / format / clarify). Social, capability,
and compose (content generation) asks skip the LLM even with assistant prior —
they are self-contained; Researcher still sees dialog for topic fill. Continuity
still sees dialog.

When ``task_kind`` is missing (tests / incomplete state), fail closed: invoke LLM
if assistant prior exists so rewrite hints are not silently dropped.

Does not inspect user phrasing.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.types import CONTENT_GENERATION_CAPABILITY, TaskKind


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
        candidate_capabilities: Sequence[str] = (),
    ) -> ContextualizerGateDecision:
        """Return whether Contextualizer must call an LLM."""
        if not has_assistant_prior:
            return ContextualizerGateDecision(invoke_llm=False, reason="no_assistant_prior")

        if requires_mcp:
            return ContextualizerGateDecision(invoke_llm=True, reason="mcp_may_need_prior")

        if task_kind is None:
            return ContextualizerGateDecision(invoke_llm=True, reason="unknown_task_kind")

        caps = {str(c).strip().lower() for c in candidate_capabilities if str(c).strip()}
        if CONTENT_GENERATION_CAPABILITY in caps:
            return ContextualizerGateDecision(invoke_llm=False, reason="self_contained:compose")

        if task_kind in cls._PRIOR_DEPENDENT_KINDS:
            return ContextualizerGateDecision(invoke_llm=True, reason=f"prior_dependent:{task_kind}")

        return ContextualizerGateDecision(invoke_llm=False, reason=f"self_contained:{task_kind}")
