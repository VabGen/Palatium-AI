# tests/unit/test_uncertainty_policy.py

"""§4 UncertaintyPolicy: incomplete inputs → one disposition (not invent)."""

from __future__ import annotations

import json

from collections import Counter
from pathlib import Path

import pytest

from palatium_ai.domain.policies.uncertainty import (
    ASSUMPTION_MARK,
    UncertaintyPolicy,
    UncertaintySignals,
)

_MANIFEST = Path(__file__).resolve().parents[1] / "fixtures" / "uncertainty" / "manifest.json"
_MIN_PER_DISPOSITION = 2


def _cases() -> list[dict[str, object]]:
    raw = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    return raw


@pytest.mark.parametrize("case", _cases(), ids=lambda c: str(c["case_id"]))
def test_uncertainty_disposition_matches_fixture(case: dict[str, object]) -> None:
    signals = UncertaintySignals.model_validate(case["signals"])
    decision = UncertaintyPolicy.decide(signals)
    assert decision.disposition == case["expected_disposition"], (
        f"{case['case_id']}: got {decision.disposition}/{decision.reason}"
    )


def test_uncertainty_manifest_covers_five_dispositions_with_floor() -> None:
    counts = Counter(str(c["expected_disposition"]) for c in _cases())
    expected = {"clarification", "default_with_mark", "honest_refusal", "proceed", "unknown"}
    assert set(counts) == expected
    for disposition, count in counts.items():
        assert count >= _MIN_PER_DISPOSITION, f"{disposition}: need ≥{_MIN_PER_DISPOSITION} fixtures (happy+edge), got {count}"


def test_prior_grounds_skips_assumption_mark() -> None:
    """Dialog-grounded identity ask must not paint ASSUMPTION_MARK (055 class)."""
    decision = UncertaintyPolicy.decide(
        UncertaintySignals(
            task_kind="knowledge_request",
            confidence=0.9,
            grounding="optional",
            has_prior_dialog=True,
            prior_grounds_answer=True,
            retrieval_empty=True,
        )
    )
    assert decision.disposition == "proceed"
    assert decision.reason == "prior_dialog_grounds"
    assert not UncertaintyPolicy.requires_assumption_mark(decision.disposition)
    assert UncertaintyPolicy.stream_prefix(decision.disposition) is None


def test_dispositions_are_mutually_exclusive_on_out_of_scope() -> None:
    """out_of_scope wins even if other signals would clarify."""
    decision = UncertaintyPolicy.decide(
        UncertaintySignals(
            task_kind="clarification_needed",
            underspecification_kind="open_text",
            requires_user_choice=True,
            confidence=0.99,
            out_of_scope=True,
            ambiguous_reference_without_prior=True,
        )
    )
    assert decision.disposition == "honest_refusal"
    assert decision.reason == "out_of_scope"


def test_unknown_resolves_to_honest_refusal_for_downstream() -> None:
    """Residual unknown is not user-facing — fallback is honest_refusal."""
    raw = UncertaintyPolicy.decide(UncertaintySignals(task_kind="knowledge_request", confidence=0.4, retrieval_empty=False))
    assert raw.disposition == "unknown"
    resolved = UncertaintyPolicy.resolve_for_downstream(raw)
    assert resolved.disposition == "honest_refusal"
    assert resolved.reason.startswith("unknown_fallback:")
    pipeline = UncertaintyPolicy.for_pipeline(
        UncertaintySignals(task_kind="knowledge_request", confidence=0.4, retrieval_empty=False)
    )
    assert pipeline.disposition == "honest_refusal"
    assert UncertaintyPolicy.resolved_disposition(raw) == "honest_refusal"


def test_assumption_mark_survives_minimal_verbosity_budget() -> None:
    """default_with_mark mark is structural — not subject to verbosity_budget."""
    assert UncertaintyPolicy.mark_exempt_from_verbosity(
        disposition="default_with_mark",
        verbosity_budget="minimal",
    )
    body = f"{ASSUMPTION_MARK}\n\nнет хитов в базе; ответ по общим правилам."
    assert UncertaintyPolicy.assumption_mark_preserved(body, disposition="default_with_mark")
    trimmed = "нет хитов в базе; ответ по общим правилам."
    assert not UncertaintyPolicy.assumption_mark_preserved(trimmed, disposition="default_with_mark")
    assert UncertaintyPolicy.assumption_mark_preserved(trimmed, disposition="honest_refusal")


def test_stream_prefix_before_first_chunk() -> None:
    """Mark must be available as a pre-stream prefix (not post-hoc on final body)."""
    assert UncertaintyPolicy.stream_prefix("default_with_mark") == f"{ASSUMPTION_MARK}\n\n"
    assert UncertaintyPolicy.stream_prefix("honest_refusal") is None
    assert UncertaintyPolicy.stream_prefix(None) is None


def test_ensure_assumption_mark_keeps_atx_heading_at_column_zero() -> None:
    """Same-line glue leaves ``##`` literal; blank line preserves CommonMark ATX."""
    body = "## Тезисный анализ Договора № 15/2026\n\nКлючевые риски."
    marked = UncertaintyPolicy.ensure_assumption_mark(body, disposition="default_with_mark")
    assert marked.startswith(f"{ASSUMPTION_MARK}\n\n")
    assert "\n\n## Тезисный анализ" in marked
    assert f"{ASSUMPTION_MARK} ##" not in marked


def test_resolve_for_downstream_is_idempotent() -> None:
    """No resolve loop: second resolve on residual or resolved is stable."""
    from palatium_ai.domain.policies.uncertainty import UncertaintyDecision

    raw = UncertaintyDecision(disposition="unknown", reason="low_confidence_in_scope")
    once = UncertaintyPolicy.resolve_for_downstream(raw)
    twice = UncertaintyPolicy.resolve_for_downstream(once)
    assert once.disposition == "honest_refusal"
    assert twice == once
    leaked = UncertaintyPolicy.coerce_for_downstream("unknown", reason="low_confidence_in_scope")
    assert leaked is not None
    again = UncertaintyPolicy.coerce_for_downstream(leaked.disposition, reason=leaked.reason)
    assert again is not None
    assert again.disposition == leaked.disposition
    assert again.reason == leaked.reason


def test_coerce_unknown_twice_yields_terminal_exhausted() -> None:
    """Second unknown (reason already fallback) → honest_refusal + exhausted, not a loop."""
    first = UncertaintyPolicy.coerce_for_downstream("unknown", reason="low_confidence_in_scope")
    assert first is not None
    assert first.disposition == "honest_refusal"
    assert first.reason.startswith("unknown_fallback:")
    # Stuck residual: still presented as unknown after a prior fallback reason.
    second = UncertaintyPolicy.coerce_for_downstream("unknown", reason=first.reason)
    assert second is not None
    assert second.disposition == "honest_refusal"
    assert second.reason == "unknown_fallback:exhausted"
    assert not UncertaintyPolicy.is_justified_refusal_reason(second.reason)


def test_justified_refusal_reasons() -> None:
    assert UncertaintyPolicy.is_justified_refusal_reason("out_of_scope")
    assert UncertaintyPolicy.is_justified_refusal_reason("required_data_absent")
    assert UncertaintyPolicy.is_justified_refusal_reason("unknown_fallback:low_confidence_in_scope")
    assert not UncertaintyPolicy.is_justified_refusal_reason("")
    assert not UncertaintyPolicy.is_justified_refusal_reason("attached")
    assert not UncertaintyPolicy.is_justified_refusal_reason("i_dont_know")
