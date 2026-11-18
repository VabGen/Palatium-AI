# src/palatium_ai/application/agents/evals/uncertainty_revisions.py

"""§4 uncertainty fixture pin — silent swap of manifest fails CI (F3)."""

from __future__ import annotations

import hashlib

from pathlib import Path
from typing import Final

from pydantic import BaseModel, Field

_REPO_ROOT = Path(__file__).resolve().parents[5]
_MANIFEST = _REPO_ROOT / "tests" / "fixtures" / "uncertainty" / "manifest.json"


class UncertaintyRevision(BaseModel, frozen=True):
    """Pinned uncertainty fixture artifact."""

    case_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    changed_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


#: Single-file manifest (8 cases). Update pin when editing the JSON.
UNCERTAINTY_REVISIONS: tuple[UncertaintyRevision, ...] = (
    UncertaintyRevision(
        case_id="uncertainty.manifest",
        relative_path="tests/fixtures/uncertainty/manifest.json",
        sha256="b70238002894a55458985f779d23dcee76589b7f0a71bc8ab73d9a2f373761d5",
        changed_on="2026-11-17",
    ),
)

UNCERTAINTY_FIXTURE_FLOOR: Final[int] = 8


def uncertainty_manifest_sha256() -> str:
    """sha256 of the uncertainty fixture manifest on disk."""
    return hashlib.sha256(_MANIFEST.read_bytes()).hexdigest()


__all__ = [
    "UNCERTAINTY_FIXTURE_FLOOR",
    "UNCERTAINTY_REVISIONS",
    "UncertaintyRevision",
    "uncertainty_manifest_sha256",
]
