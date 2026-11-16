# tests/unit/test_multi_turn_fixtures.py

"""§5 multi-turn fixtures: pins, floor, observable signals, §4 contrast / stitch."""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from palatium_ai.application.agents.evals.multi_turn.fixtures import (
    assert_expected,
    assert_pins_match,
    load_all_dialogs,
    observe,
)
from palatium_ai.application.agents.evals.multi_turn.policy import (
    MULTI_TURN_FIXTURE_FLOOR,
    MULTI_TURN_REVISIONS,
)
from palatium_ai.domain.policies.uncertainty import UncertaintyPolicy, UncertaintySignals

_UNCERTAINTY_MANIFEST = (
    Path(__file__).resolve().parents[1] / "fixtures" / "uncertainty" / "manifest.json"
)


def _by_id(case_id: str):
    return next(d for d in load_all_dialogs() if d.case_id == case_id)


def test_multi_turn_pins_and_floor() -> None:
    assert len(MULTI_TURN_REVISIONS) >= MULTI_TURN_FIXTURE_FLOOR
    assert_pins_match()
    dialogs = load_all_dialogs()
    assert len(dialogs) == len(MULTI_TURN_REVISIONS)
    assert {d.case_id for d in dialogs} == {r.case_id for r in MULTI_TURN_REVISIONS}


@pytest.mark.parametrize(
    "dialog",
    load_all_dialogs(),
    ids=lambda d: d.case_id,
)
def test_multi_turn_observable_signals(dialog: object) -> None:
    observation = observe(dialog)  # type: ignore[arg-type]
    assert_expected(dialog, observation)  # type: ignore[arg-type]


def test_contrast_pair_section4_without_prior_vs_section5_with_prior() -> None:
    """Same ask class: without prior → clarification; with prior → use prior."""
    unc = json.loads(_UNCERTAINTY_MANIFEST.read_text(encoding="utf-8"))
    without = next(c for c in unc if c["case_id"] == "like_last_time_without_history")
    without_decision = UncertaintyPolicy.decide(
        UncertaintySignals.model_validate(without["signals"])
    )
    assert without_decision.disposition == "clarification"

    with_prior = _by_id("mt_like_last_time_with_prior")
    assert with_prior.contrast_with_uncertainty_case == "like_last_time_without_history"
    obs = observe(with_prior)
    assert obs.continuation_kind == "answer"
    assert obs.trust_prior_for_workers is True
    assert obs.prior_context_present is True
    assert obs.uncertainty_disposition != "clarification"


def test_new_topic_prior_present_but_not_trusted() -> None:
    """Signal meaning: prior text may sit on the packet; new_topic must not trust it."""
    obs = observe(_by_id("mt_topic_switch"))
    assert obs.continuation_kind == "new_topic"
    assert obs.prior_context_present is True
    assert obs.trust_prior_for_workers is False


def test_reset_then_incomplete_keeps_section4_clarification() -> None:
    """After reset, Continuity does not trust prior; Uncertainty still clarifies anaphora."""
    obs = observe(_by_id("mt_reset_then_incomplete"))
    assert obs.continuation_kind == "new_topic"
    assert obs.trust_prior_for_workers is False
    assert obs.uncertainty_disposition == "clarification"


def test_refine_vs_correction_distinct_transformation() -> None:
    """Refine = format+shorten; correction = answer+none (entity fix, not a length transform).

    ``none`` is intentional SoT for correction: TransformationKind has no ``correct``
    value; rewrite would falsely claim a prose rewrite of prior. Distinguish by the
    pair (continuation_kind, transformation), not by transformation alone.
    """
    refine = observe(_by_id("mt_requirement_refine"))
    correction = observe(_by_id("mt_correction_accept"))
    assert (refine.continuation_kind, refine.transformation) == ("format", "shorten")
    assert (correction.continuation_kind, correction.transformation) == ("answer", "none")
    assert (refine.continuation_kind, refine.transformation) != (
        correction.continuation_kind,
        correction.transformation,
    )
