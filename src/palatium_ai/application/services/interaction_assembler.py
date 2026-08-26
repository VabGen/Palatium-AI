"""Assemble HITL interaction: policy plan → cleaned document (cards own selection).

Code layer (not LLM): exclusive menus become required choice mints; document
actions are never the client-side selector after assembly.
"""

from __future__ import annotations

from pydantic import BaseModel

from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.hitl.interaction_policy import HitlCardPlan, HitlInteractionPolicy
from palatium_ai.domain.mcp.models import ExecutionStrategy


class AssembledInteraction(BaseModel):
    """Result of InteractionAssembler before server mint."""

    model_config = {"frozen": True}

    document: ContentDocument | None = None
    plan: HitlCardPlan
    invalid: bool = False
    strip_exclusive_menu: bool = False


class InteractionAssembler:
    """Application orchestration over HitlInteractionPolicy (pure domain)."""

    @classmethod
    def assemble(
        cls,
        document: ContentDocument | None,
        *,
        requires_review: bool,
        selected_strategy: ExecutionStrategy | str | None = None,
        task_kind: str | None = None,
        requires_user_choice: bool = False,
    ) -> AssembledInteraction:
        """Plan cards and strip exclusive menus when choice will be minted."""
        _ = cls
        plan = HitlInteractionPolicy.plan(
            document,
            requires_review=requires_review,
            selected_strategy=selected_strategy,
            task_kind=task_kind,
            requires_user_choice=requires_user_choice,
        )
        if plan.reason == "formatter_output_invalid":
            return AssembledInteraction(
                document=document,
                plan=plan,
                invalid=True,
            )

        if document is None:
            return AssembledInteraction(document=None, plan=plan)

        if plan.choice_actions:
            framed = HitlInteractionPolicy.document_with_choice_framing(
                document,
                choice_count=len(plan.choice_actions),
            )
            clean = framed.model_copy(update={"actions": ()})
            return AssembledInteraction(
                document=clean,
                plan=plan,
                strip_exclusive_menu=True,
            )

        # No choice mint: still strip client-side actions (server cards only).
        clean = document.model_copy(update={"actions": ()})
        return AssembledInteraction(document=clean, plan=plan)


def interaction_plan_log_fields(assembled: AssembledInteraction) -> dict[str, object]:
    """Stable structured fields for hitl.interaction_plan observability."""
    plan = assembled.plan
    return {
        "reason": plan.reason,
        "choice_actions": len(plan.choice_actions),
        "mint_quality_review": plan.mint_quality_review,
        "menu_shaped": plan.menu_shaped,
        "promoted_from": plan.promoted_from,
        "force_structural": plan.force_structural,
        "required_choice": plan.required_choice,
        "invalid": assembled.invalid,
        "strip_exclusive_menu": assembled.strip_exclusive_menu,
    }
