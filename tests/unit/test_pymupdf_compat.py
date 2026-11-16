"""PyMuPDF access: no deprecated alias, no raw MuPDF noise on stderr (P5).

Live testing produced two log defects on every PDF turn:

* ``The `fitz` API is deprecated and will be removed in future`` — the adapters imported
  the deprecated alias instead of the ``pymupdf`` module it forwards to.
* ``Multiple definitions in dictionary ... key /Info`` — MuPDF writes that to stderr
  directly, so it bypassed structlog, could not be filtered per turn, and made readable
  documents look like parse failures.

Both are wiring defects, so the tests pin the wiring: the compat module resolves the real
name first, keeps the alias only as a fallback, and disables MuPDF *warnings* while leaving
errors on (035: a real render failure must stay visible).
"""

from __future__ import annotations

import sys

from types import ModuleType, SimpleNamespace

import pytest

from palatium_ai.infrastructure.parsing import pymupdf_compat


def _module_with_tools(*, warnings_calls: list[bool]) -> ModuleType:
    module = ModuleType("pymupdf")
    module.TOOLS = SimpleNamespace(  # type: ignore[attr-defined]  # fake module surface
        mupdf_display_warnings=warnings_calls.append,
    )
    return module


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pymupdf_compat, "_module", None)


def test_prefers_the_real_module_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """`pymupdf` is the supported import; `fitz` is only a forwarder."""
    calls: list[bool] = []
    fake = _module_with_tools(warnings_calls=calls)
    monkeypatch.setitem(sys.modules, "pymupdf", fake)
    monkeypatch.setitem(sys.modules, "fitz", ModuleType("fitz"))

    assert pymupdf_compat.pymupdf() is fake


def test_falls_back_to_the_alias_for_an_older_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []
    legacy = _module_with_tools(warnings_calls=calls)
    monkeypatch.setitem(sys.modules, "pymupdf", None)
    monkeypatch.setitem(sys.modules, "fitz", legacy)

    assert pymupdf_compat.pymupdf() is legacy


def test_import_failure_is_an_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A lean install must surface a typed rejection, not an AttributeError later."""
    monkeypatch.setitem(sys.modules, "pymupdf", None)
    monkeypatch.setitem(sys.modules, "fitz", None)

    with pytest.raises(ImportError, match="pymupdf is not installed"):
        pymupdf_compat.pymupdf()


def test_mupdf_warnings_are_disabled_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The /Info noise is silenced on the single import, not per document."""
    calls: list[bool] = []
    fake = _module_with_tools(warnings_calls=calls)
    monkeypatch.setitem(sys.modules, "pymupdf", fake)

    pymupdf_compat.pymupdf()
    pymupdf_compat.pymupdf()

    assert calls == [False]


def test_missing_tools_surface_is_tolerated(monkeypatch: pytest.MonkeyPatch) -> None:
    """An older/embedded build without TOOLS must still work, only noisier."""
    fake = ModuleType("pymupdf")
    monkeypatch.setitem(sys.modules, "pymupdf", fake)

    assert pymupdf_compat.pymupdf() is fake


def test_availability_probe_prefers_but_accepts_the_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def _find_spec(name: str) -> object:
        seen.append(name)
        return object() if name == "fitz" else None

    monkeypatch.setattr(pymupdf_compat, "_find_spec", _find_spec)

    assert pymupdf_compat.pymupdf_available() is True
    assert seen == ["pymupdf", "fitz"]


def test_availability_probe_is_false_without_either(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pymupdf_compat, "_find_spec", lambda _name: False)

    assert pymupdf_compat.pymupdf_available() is False
