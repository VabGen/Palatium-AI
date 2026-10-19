"""The PyJWT-shadowing guard must survive incomplete distribution metadata (025, 075).

The gate exists to fail when the abandoned ``jwt`` package shadows ``PyJWT``. It read
``dist.metadata["Name"].lower()`` for every installed distribution; on Python 3.14
``importlib.metadata`` returns ``None`` instead of raising ``KeyError`` for a missing
field, so a single local/editable distribution without ``Name`` crashed the whole quality
gate with ``AttributeError`` — the guard never reached its own check.

Both directions are pinned: a nameless distribution is skipped, and a real conflict is
still detected.
"""

from __future__ import annotations

import importlib.util
import sys

from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "ci_quality.py"


class _QualityGateModule(Protocol):
    """Only the surface of ``scripts/ci_quality.py`` these tests touch."""

    metadata: ModuleType

    def _installed_distribution_names(self) -> set[str]:
        """Gate helper under test (its leading underscore is the script's own choice)."""
        ...


def _load_module() -> _QualityGateModule:
    """Import ``scripts/ci_quality.py`` without making ``scripts`` a package."""
    spec = importlib.util.spec_from_file_location("ci_quality_under_test", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ci_quality_under_test"] = module
    spec.loader.exec_module(module)
    return cast("_QualityGateModule", module)


class _FakeMetadata(dict[str, str | None]):
    """Stands in for ``email.message.Message``: ``["Name"]`` may be ``None``."""


class _FakeDistribution:
    def __init__(self, name: str | None) -> None:
        self.metadata = _FakeMetadata({"Name": name})


def _names(monkeypatch: pytest.MonkeyPatch, module: _QualityGateModule, distributions: list[_FakeDistribution]) -> set[str]:
    monkeypatch.setattr(module.metadata, "distributions", lambda: distributions)
    return module._installed_distribution_names()


def test_nameless_distribution_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``None`` name must not abort the gate before it checks anything."""
    module = _load_module()

    assert _names(monkeypatch, module, [_FakeDistribution(None), _FakeDistribution("PyJWT")]) == {"pyjwt"}


def test_names_are_normalized_for_the_conflict_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """`jwt` + `PyJWT` must collide regardless of case, or the guard silently passes."""
    module = _load_module()

    names = _names(monkeypatch, module, [_FakeDistribution("jwt"), _FakeDistribution("PyJWT")])

    assert "jwt" in names
    assert "pyjwt" in names
