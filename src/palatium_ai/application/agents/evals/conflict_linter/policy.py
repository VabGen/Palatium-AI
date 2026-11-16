# src/palatium_ai/application/agents/evals/conflict_linter/policy.py

"""v1 policy knobs — single SoT for cutover / noqa ceiling / fixture floor."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Final

#: After this date (UTC calendar), CI job must be blocking (continue-on-error: false).
CUTOVER_DATE: Final[date] = date(2026, 12, 19)


def continue_on_error_required(*, as_of: date | None = None) -> bool:
    """True while the conflict-linter job must stay non-blocking.

    Pure calendar contract: ``as_of < CUTOVER_DATE`` → continue-on-error required.
    On/after cutover day the job must be blocking (continue-on-error absent/false).
    Pin tests parametrize ``as_of`` — do not rely on ``datetime.now()`` alone.
    """
    day = as_of if as_of is not None else datetime.now(UTC).date()
    return day < CUTOVER_DATE


#: Max conflict-linter noqa markers across AUDIT_PROMPT_REVISIONS sources (escape hatch ≠ off-switch).
NOQA_MAX: Final[int] = 5

#: Manifest must keep at least this many conflict and non-conflict fixtures (floor, not ceiling).
FIXTURE_FLOOR: Final[int] = 5

#: Soft must/may on these prompts was triaged 2026-11-16 as legitimate hierarchy
#: (must = contract/security; may = allowed flexibility) — not exclusive contradiction.
#: Heuristic limitation: it cannot tell hierarchy from exclusive choice (see plan §2).
TRIAGED_SOFT_MUST_MAY: Final[frozenset[str]] = frozenset(
    {
        "contextualizer.system",
        "critic.system",
        "researcher.system",
        "intent_classifier.system",
    }
)
