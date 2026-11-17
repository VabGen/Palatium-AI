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
        sha256="06124ce3bab866dc8fdcc5280e397f986c12ea5c72a3b1c9404aecc65d2dc796",
        changed_on="2026-11-16",
    ),
    MultiTurnRevision(
        case_id="mt_topic_switch",
        relative_path="dialogs/topic_switch.json",
        sha256="e041695067fdba7b14bdd50dc21a3be755cb2237ee99b4c62495f11da1b5c992",
        changed_on="2026-11-16",
    ),
    MultiTurnRevision(
        case_id="mt_requirement_refine",
        relative_path="dialogs/requirement_refine.json",
        sha256="9772d8178f1a290efac141115d2b5fe89102b7d19a7213a9ca8d842a9714ca77",
        changed_on="2026-11-16",
    ),
    MultiTurnRevision(
        case_id="mt_correction_accept",
        relative_path="dialogs/correction_accept.json",
        sha256="7979fa8ef220c529f0ae39478e459da786879a0095f2e91d35ce7f5b73a32559",
        changed_on="2026-11-16",
    ),
    MultiTurnRevision(
        case_id="mt_explicit_reset",
        relative_path="dialogs/explicit_reset.json",
        sha256="cf9a20974be5421c648b70d77b0c1163ab4a87bf76efa1f7cead268ca218a3d1",
        changed_on="2026-11-16",
    ),
    MultiTurnRevision(
        case_id="mt_reset_then_incomplete",
        relative_path="dialogs/reset_then_incomplete.json",
        sha256="58f0f9ef44e40e8ae35b0b323a3f3fbf290010ebe2992c2c163641213e83b1f4",
        changed_on="2026-11-16",
    ),
)
