# src/palatium_ai/domain/policies/presentation.py

"""Who owns the user-visible deliverable on one turn (single-writer contract).

The axis is orthogonal to ``StreamingContract`` and to the Formatter's generation
mode: it answers *who writes the final text*, not *how it is painted*. Exactly one
component may own it (055) — otherwise the client receives a draft and then a
rewritten answer, which is the visual replacement this wave removes.

``worker`` is eligible when the worker's answer already *is* the deliverable:
knowledge / tool / multi-step asks without a composition request. Everything that
asks for another shape (restructure, explicit response shape, choice/clarify,
verbatim extraction, revision) stays ``formatter``-owned.

The fallback to the Formatter LLM when a worker-owned turn cannot be rendered
deterministically (zero blocks, truncation, locale mismatch) is applied by the
caller — this policy only decides ownership, never quality (055).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.types import (
    RESPONSE_SHAPE_DEFAULT,
    PresentationOwner,
    ResponseShape,
    TaskKind,
    TransformationKind,
    UnderspecificationKind,
)

#: Task kinds whose answer is written by the worker when no composition is requested.
WORKER_OWNED_TASK_KINDS: frozenset[str] = frozenset(
    {"knowledge_request", "tool_execution", "multi_step_workflow"},
)


class PresentationOwnershipDecision(BaseModel):
    """Outcome of ``PresentationOwnershipPolicy`` for one turn."""

    model_config = {"frozen": True}

    owner: PresentationOwner
    reason: str = Field(min_length=1, max_length=128)


class PresentationOwnershipPolicy:
    """Pure decision: worker owns the answer unless the turn asks for composition."""

    @classmethod
    def decide(
        cls,
        *,
        task_kind: TaskKind | str,
        transformation: TransformationKind | str = "none",
        requires_user_choice: bool = False,
        underspecification_kind: UnderspecificationKind | str = "none",
        candidate_capabilities: tuple[str, ...] = (),
        revision_requested: bool = False,
        response_shape: ResponseShape | str = RESPONSE_SHAPE_DEFAULT,
        rollout_allows: bool = True,
    ) -> PresentationOwnershipDecision:
        """Return the single writer for the turn (deterministic, no I/O)."""
        if not rollout_allows:
            return cls._formatter("rollout_excluded")
        if task_kind not in WORKER_OWNED_TASK_KINDS:
            return cls._formatter("task_kind")
        blockers = (
            (transformation == "restructure", "restructure_requested"),
            (requires_user_choice, "requires_user_choice"),
            (underspecification_kind != "none", "underspecified"),
            (revision_requested, "revision_requested"),
            (response_shape != RESPONSE_SHAPE_DEFAULT, "shape_requested"),
            (
                "verbatim_extraction" in {cap.strip().lower() for cap in candidate_capabilities},
                "verbatim_requested",
            ),
        )
        for failed, reason in blockers:
            if failed:
                return cls._formatter(reason)
        return PresentationOwnershipDecision(owner="worker", reason="eligible")

    @staticmethod
    def _formatter(reason: str) -> PresentationOwnershipDecision:
        return PresentationOwnershipDecision(owner="formatter", reason=reason)
