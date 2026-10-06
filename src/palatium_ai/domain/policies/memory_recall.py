# src/palatium_ai/domain/policies/memory_recall.py

"""When durable memory recall may run on the hot path (latency, 055).

Intent-first graph: classify before recall. Low-risk / self-contained kinds skip
durable search (scratchpad pins may still apply). Fail closed when task_kind is
unknown — recall rather than silently starve Continuity/Contextualizer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.types import TaskKind


class MemoryRecallDecision(BaseModel):
    """Outcome of MemoryRecallPolicy for one turn."""

    model_config = {"frozen": True}

    allowed: bool
    reason: str = Field(min_length=1, max_length=128)


class MemoryRecallPolicy:
    """Pure domain policy: task_kind → durable memory search or skip."""

    _SKIP_KINDS: frozenset[str] = frozenset(
        {
            "social_conversation",
            "capability_discovery",
            "response_formatting",
            "clarification_needed",
        }
    )

    @classmethod
    def decide(
        cls,
        *,
        task_kind: TaskKind | None,
        requires_mcp: bool,
    ) -> MemoryRecallDecision:
        """Return whether durable recall (pgvector/FTS) should run."""
        if requires_mcp:
            return MemoryRecallDecision(allowed=True, reason="requires_mcp")
        if task_kind is None:
            return MemoryRecallDecision(allowed=True, reason="unknown_task_kind")
        if task_kind in cls._SKIP_KINDS:
            return MemoryRecallDecision(allowed=False, reason=f"skip:{task_kind}")
        return MemoryRecallDecision(allowed=True, reason=f"recall:{task_kind}")
