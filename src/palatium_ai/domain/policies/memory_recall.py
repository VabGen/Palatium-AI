# src/palatium_ai/domain/policies/memory_recall.py

"""When durable memory recall may run on the hot path (latency, 055).

Intent-first graph: classify before recall. Recall is the default — memory is what
lets a history-blind Intent label be disambiguated downstream:

- ``clarification_needed`` ALWAYS recalls: Contextualizer / Continuity need durable
  context precisely to decide whether the "missing" slot is already known.
- ``social_conversation`` / ``capability_discovery`` recall preferences only
  (name, tone, tool prefs) — personalisation without a fact dump.
- ``response_formatting`` is the only skip: the turn transforms prior assistant
  content; injecting memory facts would let the presentation layer change meaning.
- A content transform (``expand`` / ``shorten`` / ``rewrite``) reads the prior
  assistant answer as its source, so facts and pinned thread intents are not
  evidence either: recall narrows to preferences (personalisation), and pinned
  intents are filtered with the same kind set. Without this a stale pin
  («сравни файлы») steers the rewrite into the old topic.

Fail closed when task_kind is unknown — recall rather than silently starve
Continuity/Contextualizer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.memory.types import MemoryType
from palatium_ai.domain.policies.transform import TransformPolicy
from palatium_ai.domain.policies.types import TRANSFORMATION_DEFAULT, TaskKind, TransformationKind

# Narrow Select: user preferences only (060/065) — personalise, do not dump facts.
_PREFERENCE_RECALL_KINDS: tuple[MemoryType, ...] = ("preference",)


class MemoryRecallDecision(BaseModel):
    """Outcome of MemoryRecallPolicy for one turn."""

    model_config = {"frozen": True}

    allowed: bool
    reason: str = Field(min_length=1, max_length=128)
    # None = all MemoryType values; non-empty = post-filter durable hits by kind.
    kinds: tuple[MemoryType, ...] | None = None
    # None = pinned thread intents stay (query-independent notes); non-empty = filter
    # scratchpad pins too. Only a content transform narrows pins: they are ask history,
    # not personalisation, and would re-open the previous topic.
    pin_kinds: tuple[MemoryType, ...] | None = None


class MemoryRecallPolicy:
    """Pure domain policy: task_kind → durable memory search or skip."""

    _SKIP_KINDS: frozenset[str] = frozenset({"response_formatting"})
    _PREFERENCE_ONLY_KINDS: frozenset[str] = frozenset({"capability_discovery", "social_conversation"})

    @classmethod
    def decide(
        cls,
        *,
        task_kind: TaskKind | None,
        requires_mcp: bool,
        transformation: TransformationKind | str | None = TRANSFORMATION_DEFAULT,
    ) -> MemoryRecallDecision:
        """Return whether durable recall (pgvector/FTS + L4 graph) should run."""
        if TransformPolicy.needs_reason_over_prior(transformation):
            kind = TransformPolicy.coerce(transformation)
            # The prior answer is the only source of a content transform: a fact or a
            # pinned ask from earlier turns is stale topic evidence (055).
            return MemoryRecallDecision(
                allowed=True,
                reason=f"transform:{kind}:preference",
                kinds=_PREFERENCE_RECALL_KINDS,
                pin_kinds=_PREFERENCE_RECALL_KINDS,
            )
        if requires_mcp:
            return MemoryRecallDecision(allowed=True, reason="requires_mcp")
        if task_kind is None:
            return MemoryRecallDecision(allowed=True, reason="unknown_task_kind")
        if task_kind in cls._PREFERENCE_ONLY_KINDS:
            return MemoryRecallDecision(
                allowed=True,
                reason=f"recall:{task_kind}:preference",
                kinds=_PREFERENCE_RECALL_KINDS,
            )
        if task_kind in cls._SKIP_KINDS:
            return MemoryRecallDecision(allowed=False, reason=f"skip:{task_kind}")
        return MemoryRecallDecision(allowed=True, reason=f"recall:{task_kind}")
