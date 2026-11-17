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

Pin hygiene (Anthropic / MS 2026 Select-as-risk; 060/065 anti context-dump):
scratchpad slots are raw short user turns, mostly completed *asks*, not durable
prefs. They must not ride every later turn as standing instructions. Narrow pins
to preferences when Continuity marks a new topic, when prior is untrusted for
workers, when this turn carries its own upload fence, or on social/capability.

Fail closed when task_kind is unknown — recall rather than silently starve
Continuity/Contextualizer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from palatium_ai.domain.memory.types import MemoryType
from palatium_ai.domain.policies.transform import TransformPolicy
from palatium_ai.domain.policies.types import TRANSFORMATION_DEFAULT, TaskKind, TransformationKind

if TYPE_CHECKING:
    from palatium_ai.domain.policies.types import ContinuationKind

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
        use_memory: bool = True,
    ) -> MemoryRecallDecision:
        """Return whether durable recall (pgvector/FTS + L4 graph) should run."""
        # W11 / ChatGPT Temporary Unpersonalized: hide durable personalization;
        # same-thread dialog + scratchpad still flow via other state keys.
        if not use_memory:
            return MemoryRecallDecision(allowed=False, reason="use_memory_disabled")
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
            # Pins and durable hits share the preference gate: scratchpad stores raw
            # short asks as kind=fact, and leaving pin_kinds=None let those asks
            # become standing agendas on «привет» / capability turns (055).
            return MemoryRecallDecision(
                allowed=True,
                reason=f"recall:{task_kind}:preference",
                kinds=_PREFERENCE_RECALL_KINDS,
                pin_kinds=_PREFERENCE_RECALL_KINDS,
            )
        if task_kind in cls._SKIP_KINDS:
            return MemoryRecallDecision(allowed=False, reason=f"skip:{task_kind}")
        return MemoryRecallDecision(allowed=True, reason=f"recall:{task_kind}")

    @classmethod
    def apply_pin_hygiene(
        cls,
        decision: MemoryRecallDecision,
        *,
        continuation_kind: ContinuationKind | str | None = None,
        trust_prior_for_workers: bool = False,
        has_turn_attachments: bool = False,
    ) -> MemoryRecallDecision:
        """Drop stale scratchpad asks when this turn must not inherit prior tasks.

        Structural only (055): Continuity ``new_topic`` / untrusted prior, or a
        fresh upload fence. Preferences still personalise. Already-narrowed
        decisions (transform / social) are left unchanged.
        """
        if not decision.allowed or decision.pin_kinds is not None:
            return decision
        if has_turn_attachments:
            # Current fence is the evidence; pinned prior asks are a different task.
            return decision.model_copy(
                update={
                    "pin_kinds": _PREFERENCE_RECALL_KINDS,
                    "reason": f"{decision.reason}+pins:preference:turn_attachments"[:128],
                }
            )
        kind = str(continuation_kind or "").strip()
        # ``new_topic`` is the Continuity signal that prior task pins must not steer.
        # ``clarify`` / trusted ``answer``|``format`` keep pins — anaphora may need them.
        if kind == "new_topic" or (kind in {"answer", "format"} and not trust_prior_for_workers):
            label = kind if kind == "new_topic" else f"{kind}:untrusted"
            return decision.model_copy(
                update={
                    "pin_kinds": _PREFERENCE_RECALL_KINDS,
                    "reason": f"{decision.reason}+pins:preference:{label}"[:128],
                }
            )
        return decision


__all__ = ["MemoryRecallDecision", "MemoryRecallPolicy"]
