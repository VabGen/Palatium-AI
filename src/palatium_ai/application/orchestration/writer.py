# src/palatium_ai/application/orchestration/writer.py

"""Resolve the single answer writer for one turn (P1a, 055).

The decision is made once, before any worker runs, and stored in graph state so
every node paints under the same contract: the researcher must not stream a draft
that the Formatter will later own, and the Formatter must not call an LLM for a
document it only has to render.

Two keys, sticky by ``thread_id`` (``ANSWER_WRITER_MODE`` / ``ANSWER_WRITER_ROLLOUT_PCT``):
a thread keeps its writer for the whole dialog, so a rolling deploy cannot flip a
conversation into a second writer mid-answer.
"""

from __future__ import annotations

from palatium_ai.application.orchestration import selectors
from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.core.config.settings import get_settings
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.rollout import is_in_rollout
from palatium_ai.domain.policies.presentation import (
    PresentationOwnershipDecision,
    PresentationOwnershipPolicy,
)
from palatium_ai.domain.policies.types import PRESENTATION_OWNER_DEFAULT

logger = get_logger(__name__)


def resolve_presentation_owner(state: AgentGraphState) -> PresentationOwnershipDecision:
    """Decide (and account for) the writer of this turn — safe default: formatter."""
    settings = get_settings().answer
    if settings.writer_mode != "worker":
        return PresentationOwnershipDecision(owner="formatter", reason="mode_formatter")
    thread_id = selectors.resolved_thread_id(state)
    if not is_in_rollout(thread_id, settings.writer_rollout_pct):
        return PresentationOwnershipDecision(owner="formatter", reason="rollout_excluded")
    return PresentationOwnershipPolicy.decide(
        task_kind=selectors.resolved_task_kind(state),
        transformation=selectors.resolved_transformation(state),
        requires_user_choice=selectors.requires_user_choice(state),
        underspecification_kind=selectors.underspecification_kind(state),
        candidate_capabilities=selectors.resolved_candidate_capabilities(state),
        revision_requested=selectors.resolved_revision_feedback(state) is not None,
        response_shape=selectors.resolved_response_shape(state),
    )


def decide_and_record(state: AgentGraphState) -> PresentationOwnershipDecision:
    """Resolve the writer once per turn and emit its metric/log (040)."""
    decision = resolve_presentation_owner(state)
    agent_metrics.record_answer_writer(owner=decision.owner, reason=decision.reason)
    logger.info(
        "answer.writer",
        writer=decision.owner,
        reason=decision.reason,
        thread_id=selectors.resolved_thread_id(state),
    )
    return decision


def current_owner(state: AgentGraphState) -> str:
    """Writer recorded on the turn, or the safe default when weaving never ran."""
    owner = state.get("presentation_owner")
    return owner if isinstance(owner, str) and owner else PRESENTATION_OWNER_DEFAULT
