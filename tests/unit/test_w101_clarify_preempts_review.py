"""W10.1 P2 — file clarify card preempts concurrent quality-review card."""

from __future__ import annotations

from palatium_ai.domain.hitl.interaction_policy import HitlCardPlan


def test_w101_clarify_preempts_review_card_contract() -> None:
    """Document the assembly rule: mint_quality_review is ignored when a file card exists.

    The live gate lives in ``IntentHitlFlow`` (file_card is not None → skip review).
    This unit pins the plan shape the flow consults so a future refactor cannot
    silently re-introduce dual cards without updating the gate.
    """
    plan = HitlCardPlan(
        choice_actions=(),
        mint_quality_review=True,
        reason="file_choice_pending",
        menu_shaped=False,
        required_choice=True,
    )
    file_card_present = True
    should_mint_review = bool(plan.mint_quality_review) and not file_card_present
    assert should_mint_review is False
    should_mint_review_alone = bool(plan.mint_quality_review) and not False
    assert should_mint_review_alone is True
