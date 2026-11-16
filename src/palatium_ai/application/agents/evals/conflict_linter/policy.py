# src/palatium_ai/application/agents/evals/conflict_linter/policy.py

"""v1 policy knobs — single SoT for cutover / noqa ceiling / fixture floor."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Final, Literal

from pydantic import BaseModel, Field

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


#: Soft must/may triage signatures (exact match on prompt_id + kind — never path substring).
#: Triaged 2026-11-16 as legitimate hierarchy (must = contract/security; may = flexibility).
#: Heuristic cannot tell hierarchy from exclusive choice (see plan §2).
class TriagedSoftSignature(BaseModel, frozen=True):
    """Exact soft-finding identity for cutover ``soft_triaged`` accounting."""

    prompt_id: str = Field(min_length=1)
    kind: Literal["must_may"] = "must_may"


TRIAGED_SOFT_MUST_MAY: Final[frozenset[TriagedSoftSignature]] = frozenset(
    {
        TriagedSoftSignature(prompt_id="contextualizer.system"),
        TriagedSoftSignature(prompt_id="critic.system"),
        TriagedSoftSignature(prompt_id="researcher.system"),
        TriagedSoftSignature(prompt_id="intent_classifier.system"),
    }
)


def is_triaged_soft(*, prompt_id: str | None, kind: str) -> bool:
    """True when finding matches a triage signature exactly (prompt_id + kind)."""
    if prompt_id is None or kind != "must_may":
        return False
    return TriagedSoftSignature(prompt_id=prompt_id, kind="must_may") in TRIAGED_SOFT_MUST_MAY


def soft_metric_breakdown(
    soft: Sequence[object],
) -> tuple[int, int, int]:
    """Return ``(soft_raw, soft_triaged, soft_new)`` for soft findings.

    Each item must expose ``prompt_id`` and ``kind`` (ConflictFinding or compatible).
    """
    raw = len(soft)
    triaged = 0
    for item in soft:
        prompt_id = getattr(item, "prompt_id", None)
        kind = getattr(item, "kind", "")
        if is_triaged_soft(prompt_id=prompt_id if isinstance(prompt_id, str) else None, kind=str(kind)):
            triaged += 1
    return raw, triaged, raw - triaged
