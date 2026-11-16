# src/palatium_ai/application/agents/evals/multi_turn/fixtures.py

"""Load §5 dialog fixtures and evaluate observable signals (no LLM, no answer text).

Conductivity pattern from §4: history → ContinuityPolicy + UncertaintyPolicy → fields.
Frozen Contextualizer/Intent stubs are hand-authored in the fixture — not LLM output.
"""

from __future__ import annotations

import hashlib
import json

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from palatium_ai.application.agents.evals.multi_turn.policy import (
    MULTI_TURN_FIXTURE_FLOOR,
    MULTI_TURN_MAX_TURNS,
    MULTI_TURN_REVISIONS,
)
from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.memory.contextualizer import ContextualizerOutput
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.domain.policies.continuity import ContinuityPolicy
from palatium_ai.domain.policies.types import TransformationKind
from palatium_ai.domain.policies.uncertainty import UncertaintyPolicy, UncertaintySignals

#: …/evals/multi_turn → src/palatium_ai/application/agents/evals/multi_turn (6↑ = repo root)
_FIXTURES_ROOT = Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "multi_turn"
_DIALOGS_DIR = _FIXTURES_ROOT / "dialogs"


class MultiTurnExpected(BaseModel, frozen=True):
    """Observable signals only — never full expected answer prose.

    ``trust_prior_for_workers`` is the «used prior» signal. ``prior_context_present``
    only means EffectiveRoutingIntent still carries dialog text (often true on
    new_topic too); do not treat it alone as continuity success.
    """

    continuation_kind: str
    trust_prior_for_workers: bool
    prior_context_present: bool
    uncertainty_disposition: str
    transformation: TransformationKind | None = None
    underspecification_kind: str | None = None


class MultiTurnDialog(BaseModel, frozen=True):
    """One hand-authored multi-turn case (2–4 turns)."""

    case_id: str = Field(min_length=1)
    note: str = Field(min_length=1)
    turns: list[dict[str, str]] = Field(min_length=2)
    check_turn_index: int = Field(ge=0)
    frozen: dict[str, Any]
    expected: MultiTurnExpected
    contrast_with_uncertainty_case: str | None = None


class MultiTurnObservation(BaseModel, frozen=True):
    """Signals produced by policies on the check turn."""

    continuation_kind: str
    trust_prior_for_workers: bool
    prior_context_present: bool
    uncertainty_disposition: str
    transformation: TransformationKind
    underspecification_kind: str


def fixtures_root() -> Path:
    return _FIXTURES_ROOT


def load_dialog(path: Path) -> MultiTurnDialog:
    raw = json.loads(path.read_text(encoding="utf-8"))
    dialog = MultiTurnDialog.model_validate(raw)
    if not (2 <= len(dialog.turns) <= MULTI_TURN_MAX_TURNS):
        msg = f"{dialog.case_id}: need 2..{MULTI_TURN_MAX_TURNS} turns, got {len(dialog.turns)}"
        raise ValueError(msg)
    if dialog.check_turn_index >= len(dialog.turns):
        msg = f"{dialog.case_id}: check_turn_index out of range"
        raise ValueError(msg)
    if dialog.turns[dialog.check_turn_index].get("role") != "user":
        msg = f"{dialog.case_id}: check turn must be user"
        raise ValueError(msg)
    return dialog


def load_all_dialogs() -> list[MultiTurnDialog]:
    paths = sorted(_DIALOGS_DIR.glob("*.json"))
    if len(paths) < MULTI_TURN_FIXTURE_FLOOR:
        msg = f"multi-turn floor {MULTI_TURN_FIXTURE_FLOOR} not met ({len(paths)} dialogs)"
        raise ValueError(msg)
    return [load_dialog(p) for p in paths]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_pins_match() -> None:
    """Silent dialog swap fails — same contract as AUDIT_PROMPT_REVISIONS."""
    by_id = {r.case_id: r for r in MULTI_TURN_REVISIONS}
    dialogs = load_all_dialogs()
    if len(dialogs) != len(MULTI_TURN_REVISIONS):
        msg = (
            f"dialog count {len(dialogs)} != MULTI_TURN_REVISIONS {len(MULTI_TURN_REVISIONS)}"
        )
        raise AssertionError(msg)
    for dialog in dialogs:
        pin = by_id.get(dialog.case_id)
        if pin is None:
            msg = f"missing pin for {dialog.case_id}"
            raise AssertionError(msg)
        path = _FIXTURES_ROOT / pin.relative_path
        digest = file_sha256(path)
        if digest != pin.sha256:
            msg = (
                f"{dialog.case_id} sha256 drift: got {digest}, pin {pin.sha256} "
                f"— update MULTI_TURN_REVISIONS if intentional"
            )
            raise AssertionError(msg)


def _window_before_check(dialog: MultiTurnDialog) -> DialogTurnWindow:
    """History visible at check turn (turns strictly before check)."""
    thread_id = f"mt-{dialog.case_id}"
    prior = dialog.turns[: dialog.check_turn_index]
    built: list[DialogTurn] = []
    for seq, turn in enumerate(prior):
        built.append(
            DialogTurn(
                id=uuid4(),
                thread_id=thread_id,
                role=turn["role"],  # type: ignore[arg-type]
                content=turn["content"],
                seq=seq,
                created_at=datetime.now(UTC),
            )
        )
    return DialogTurnWindow(thread_id=thread_id, turns=tuple(built), limit=12)


def _intent_from_frozen(raw: dict[str, Any]) -> IntentClassifierOutput:
    return IntentClassifierOutput(
        task_kind=raw["task_kind"],
        requires_mcp=bool(raw.get("requires_mcp", False)),
        requires_user_choice=bool(raw.get("requires_user_choice", False)),
        underspecification_kind=raw.get("underspecification_kind", "none"),
        confidence=float(raw["confidence"]),
        grounding=raw.get("grounding", "optional"),
        transformation=raw.get("transformation", "none"),
        reasoning=str(raw.get("reasoning", "multi_turn_fixture")),
    )


def _contextualizer_from_frozen(raw: dict[str, Any]) -> ContextualizerOutput:
    return ContextualizerOutput(
        rewritten_query=str(raw["rewritten_query"]),
        continuation_kind=raw["continuation_kind"],
        confidence=float(raw["confidence"]),
        refers_to_prior=bool(raw.get("refers_to_prior", False)),
        prior_assistant_excerpt=raw.get("prior_assistant_excerpt"),
        reasoning=str(raw.get("reasoning", "multi_turn_fixture")),
    )


def observe(dialog: MultiTurnDialog) -> MultiTurnObservation:
    """Eval-only harness: Continuity + Uncertainty on **frozen** stubs.

    Does **not** exercise Contextualizer/Intent LLM prompts or live graph wiring.
    ``MULTI_TURN_REVISIONS`` pins fixture JSON only — agent wiring is a separate §5 PR.
    """
    window = _window_before_check(dialog)
    check = dialog.turns[dialog.check_turn_index]
    user_text = check["content"]
    ctx = _contextualizer_from_frozen(dialog.frozen["contextualizer"])
    intent = _intent_from_frozen(dialog.frozen["raw_intent"])
    effective = ContinuityPolicy.resolve(
        contextualizer=ctx,
        dialog=window,
        raw_intent=intent,
        user_text=user_text,
    )
    decision = UncertaintyPolicy.for_pipeline(
        UncertaintySignals.model_validate(dialog.frozen["uncertainty_signals"])
    )
    return MultiTurnObservation(
        continuation_kind=effective.continuation_kind,
        trust_prior_for_workers=effective.trust_prior_for_workers,
        prior_context_present=bool((effective.prior_context or "").strip()),
        uncertainty_disposition=UncertaintyPolicy.resolved_disposition(decision),
        transformation=effective.transformation,
        underspecification_kind=effective.underspecification_kind,
    )


def assert_expected(dialog: MultiTurnDialog, observation: MultiTurnObservation) -> None:
    exp = dialog.expected
    if observation.continuation_kind != exp.continuation_kind:
        msg = (
            f"{dialog.case_id}: continuation_kind {observation.continuation_kind} "
            f"!= {exp.continuation_kind}"
        )
        raise AssertionError(msg)
    if observation.trust_prior_for_workers is not exp.trust_prior_for_workers:
        msg = f"{dialog.case_id}: trust_prior mismatch"
        raise AssertionError(msg)
    if observation.prior_context_present is not exp.prior_context_present:
        msg = f"{dialog.case_id}: prior_context_present mismatch"
        raise AssertionError(msg)
    if observation.uncertainty_disposition != exp.uncertainty_disposition:
        msg = (
            f"{dialog.case_id}: disposition {observation.uncertainty_disposition} "
            f"!= {exp.uncertainty_disposition}"
        )
        raise AssertionError(msg)
    if exp.transformation is not None and observation.transformation != exp.transformation:
        msg = f"{dialog.case_id}: transformation mismatch"
        raise AssertionError(msg)
    if (
        exp.underspecification_kind is not None
        and observation.underspecification_kind != exp.underspecification_kind
    ):
        msg = f"{dialog.case_id}: underspec mismatch"
        raise AssertionError(msg)
