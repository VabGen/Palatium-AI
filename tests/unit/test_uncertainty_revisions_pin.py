# tests/unit/test_uncertainty_revisions_pin.py

"""§4 F3: uncertainty manifest sha256 pin (same pattern as MULTI_TURN_REVISIONS)."""

from __future__ import annotations

import json

from pathlib import Path

from palatium_ai.application.agents.evals.uncertainty_revisions import (
    UNCERTAINTY_FIXTURE_FLOOR,
    UNCERTAINTY_REVISIONS,
    uncertainty_manifest_sha256,
)

_MANIFEST = Path(__file__).resolve().parents[1] / "fixtures" / "uncertainty" / "manifest.json"


def test_uncertainty_revisions_pin() -> None:
    assert len(UNCERTAINTY_REVISIONS) == 1
    rev = UNCERTAINTY_REVISIONS[0]
    assert uncertainty_manifest_sha256() == rev.sha256
    cases = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(cases, list)
    assert len(cases) >= UNCERTAINTY_FIXTURE_FLOOR
