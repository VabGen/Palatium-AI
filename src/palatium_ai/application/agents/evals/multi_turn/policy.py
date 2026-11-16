# src/palatium_ai/application/agents/evals/multi_turn/policy.py

"""§5 multi-turn fixture floor + sha256 pins (hand-authored dialogs)."""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, Field

#: Floor, not ceiling — expand after triage (same pattern as conflict fixtures).
MULTI_TURN_FIXTURE_FLOOR: Final[int] = 5

#: Max turns per dialog (setup → trigger → check stays diagnosable).
MULTI_TURN_MAX_TURNS: Final[int] = 4


class MultiTurnRevision(BaseModel, frozen=True):
    """Pinned dialog artifact — silent swap fails CI."""

    case_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    changed_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


#: Update pin when editing a dialog under tests/fixtures/multi_turn/dialogs/.
MULTI_TURN_REVISIONS: tuple[MultiTurnRevision, ...] = (
    MultiTurnRevision(
        case_id="mt_like_last_time_with_prior",
        relative_path="dialogs/like_last_time_with_prior.json",
        sha256="a1df7eda83d907cbbe3a0fbfa61f3a1e57232bbfba205bb5069fa36eb78c828c",
        changed_on="2026-11-16",
    ),
    MultiTurnRevision(
        case_id="mt_topic_switch",
        relative_path="dialogs/topic_switch.json",
        sha256="4fbe8597900283555e9f01c95e951d1e5e5768e1540f191c75b357120a51c225",
        changed_on="2026-11-16",
    ),
    MultiTurnRevision(
        case_id="mt_requirement_refine",
        relative_path="dialogs/requirement_refine.json",
        sha256="eb6c18856f86c917209140ab60ca2ee0ccefa2ec173f223edff4b4a6e491bdfa",
        changed_on="2026-11-16",
    ),
    MultiTurnRevision(
        case_id="mt_correction_accept",
        relative_path="dialogs/correction_accept.json",
        sha256="7b15c38624aa6810ebb9cdb8c48eab1072315034617f06f05f9ec089638bdd7b",
        changed_on="2026-11-16",
    ),
    MultiTurnRevision(
        case_id="mt_explicit_reset",
        relative_path="dialogs/explicit_reset.json",
        sha256="b69a3f80bdf7c015ac012ca7dd1ef36c5b03cc33f094add6087a848db99252ca",
        changed_on="2026-11-16",
    ),
    MultiTurnRevision(
        case_id="mt_reset_then_incomplete",
        relative_path="dialogs/reset_then_incomplete.json",
        sha256="58f0f9ef44e40e8ae35b0b323a3f3fbf290010ebe2992c2c163641213e83b1f4",
        changed_on="2026-11-16",
    ),
)
