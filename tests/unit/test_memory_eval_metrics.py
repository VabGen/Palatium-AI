# tests/unit/test_memory_eval_metrics.py

"""Offline memory eval metrics (M9 step 1): supersede precision/recall, reinforcement lift."""

from __future__ import annotations

import pytest

from palatium_ai.domain.memory.eval_metrics import (
    reinforcement_lift,
    supersede_precision,
    supersede_recall,
)


def test_supersede_precision_counts_only_warranted_actions() -> None:
    expected = frozenset({"k1", "k2"})
    assert supersede_precision(superseded_keys=["k1", "k2"], expected_keys=expected) == pytest.approx(1.0)
    # One warranted, one gratuitous → half of what was done was wrong.
    assert supersede_precision(superseded_keys=["k1", "k9"], expected_keys=expected) == pytest.approx(0.5)


def test_supersede_precision_without_any_action_is_one() -> None:
    """A batch that superseded nothing did not supersede anything wrongly."""
    assert supersede_precision(superseded_keys=[], expected_keys=frozenset({"k1"})) == 1.0


def test_supersede_recall_sees_a_missed_contradiction() -> None:
    """Precision alone cannot: doing nothing would score 1.0 there and 0.0 here."""
    expected = frozenset({"k1", "pii-1"})
    assert supersede_recall(superseded_keys=["k1"], expected_keys=expected) == pytest.approx(0.5)
    assert supersede_recall(superseded_keys=[], expected_keys=expected) == 0.0
    assert supersede_recall(superseded_keys=["x"], expected_keys=frozenset()) == 1.0


def test_reinforcement_lift_measures_the_selection_delta() -> None:
    """Reinforced cohort selected twice as often → +0.5 lift; always/never → 1.0."""
    reinforced = [True, True, False, False]
    selected = [True, False, True, False]
    assert reinforcement_lift(reinforced=reinforced, selected=selected) == pytest.approx(0.0)
    half_vs_none = [True, False, False, False]
    assert reinforcement_lift(reinforced=reinforced, selected=half_vs_none) == pytest.approx(0.5)
    always_vs_never = [True, True, False, False]
    assert reinforcement_lift(reinforced=reinforced, selected=always_vs_never) == pytest.approx(1.0)


def test_reinforcement_lift_is_undefined_without_a_control_group() -> None:
    """``None``, not 0.0: no control cohort means no measurement (050)."""
    assert reinforcement_lift(reinforced=[True, True], selected=[True, False]) is None
    assert reinforcement_lift(reinforced=[False, False], selected=[True, False]) is None


def test_reinforcement_lift_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="same facts"):
        reinforcement_lift(reinforced=[True, False], selected=[True])
