"""The debt-marker gate must be able to *fail* (086, 075, 050).

``scripts/check_todos.py`` is the enforcement half of rule 086: a marker without an owner,
a verifiable ticket and a date is not a record, and the gate is what keeps that from being
a matter of reviewer memory. The negative cases are pinned here because the failure mode
is silent — a gate that stops recognising a bare marker stays green while the debt it was
supposed to track disappears from view.

Markers in this file are **assembled at runtime** (``_MARKER`` below). ``tests/`` is inside
the gate's own scan scope, so a literal malformed marker would be reported by the very gate
these tests exercise, and exempting this file would remove the rule exactly where it is
most likely to be needed next.
"""

from __future__ import annotations

import importlib.util
import sys

from datetime import date, timedelta
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "check_todos.py"

# Split so the source line does not itself read as a marker to the scanner under test.
_MARKER = "TODO"
_VALID_TICKET = "plans/cursor-rules-hardening §5"


def _load_module() -> ModuleType:
    """Import ``scripts/check_todos.py`` without making ``scripts`` a package."""
    spec = importlib.util.spec_from_file_location("check_todos_under_test", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_todos_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _bare(separator: str, marker: str = _MARKER) -> str:
    """A marker that is a note, not a record."""
    return f"# {marker}{separator} fix this someday"


def _record(owner: str, ticket: str, day: str, marker: str = _MARKER) -> str:
    """A well-formed record, built from parts."""
    return f"# {marker}({owner}, {ticket}, {day}): fix this"


def _inspect(line: str, today: date | None = None) -> tuple[list, list]:
    module = _load_module()
    return module._inspect_line("sample.py", 7, line, today or date.today())


def _messages(line: str, today: date | None = None) -> list[str]:
    findings, _ = _inspect(line, today)
    return [finding.message for finding in findings]


@pytest.mark.parametrize("separator", (":", "("))
def test_bare_marker_is_rejected(separator: str) -> None:
    """Both shapes of a bare note must be caught, not just the colon one."""
    assert _messages(_bare(separator)) == [f"{_MARKER} without (owner, ticket, date) - see rule 086"]


@pytest.mark.parametrize("marker", ("FIXME", "XXX", "HACK"))
def test_every_marker_word_is_gated(marker: str) -> None:
    """Singling out one word would just move the debt to its synonym."""
    text = f"# {marker}: rework this"

    assert len(_messages(text)) == 1


def test_well_formed_record_is_accepted() -> None:
    """A record carries owner, ticket and date — and yields them for the age report."""
    findings, records = _inspect(_record("platform/backend", _VALID_TICKET, "2026-09-01"))

    assert findings == []
    assert [(record.owner, record.ticket, record.day) for record in records] == [
        ("platform/backend", _VALID_TICKET, date(2026, 9, 1))
    ]


def test_future_date_is_rejected() -> None:
    """A date nobody could have written is a typo or a way to dodge the age report."""
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    assert _messages(_record("o", _VALID_TICKET, tomorrow)) == [f"date {tomorrow} is in the future"]


def test_unparseable_date_is_rejected() -> None:
    """The date field must still be checkable once matched."""
    text = f"# {_MARKER}(o, {_VALID_TICKET}, 2026-13-45): fix"

    assert _messages(text) == ["date '2026-13-45' is not a valid ISO-8601 date"]


def test_vague_ticket_is_rejected() -> None:
    """«later» is not a reference; without this the gate would accept a shrug."""
    findings, records = _inspect(_record("team", "later", "2026-09-01"))

    assert records == []
    assert len(findings) == 1
    assert "must be #<issue> or a path" in findings[0].message


def test_issue_ticket_is_accepted() -> None:
    """A tracker reference cannot be verified offline, so it is taken at face value."""
    findings, records = _inspect(_record("platform/backend", "#412", "2026-09-01"))

    assert findings == []
    assert len(records) == 1


def test_dangling_ticket_path_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The point of the path form: it can be verified, so a dead reference fails."""
    module = _load_module()
    monkeypatch.setattr(module, "_ROOT", tmp_path)
    (tmp_path / "plans").mkdir()

    findings, records = module._inspect_line(
        "sample.py", 1, _record("team", "plans/missing-plan §2", "2026-09-01"), date.today()
    )

    assert records == []
    assert len(findings) == 1
    assert "'plans/missing-plan'" in findings[0].message


def test_existing_ticket_path_is_accepted_without_extension(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`plans/<file> §N` and `.cursor/`-relative references must both resolve."""
    module = _load_module()
    monkeypatch.setattr(module, "_ROOT", tmp_path)
    (tmp_path / "plans").mkdir()
    (tmp_path / ".cursor" / "docs").mkdir(parents=True)
    (tmp_path / "plans" / "roadmap.md").write_text("x", encoding="utf-8")
    (tmp_path / ".cursor" / "docs" / "spec.md").write_text("x", encoding="utf-8")

    for ticket in ("plans/roadmap §4", "docs/spec.md#L10"):
        findings, records = module._inspect_line("sample.py", 1, _record("team", ticket, "2026-09-01"), date.today())
        assert findings == [], (ticket, findings)
        assert len(records) == 1


def test_bare_marker_beside_a_valid_record_is_still_reported() -> None:
    """Removing the records first is what keeps one good line from hiding a second marker."""
    line = f"{_record('team', _VALID_TICKET, '2026-09-01')}  # {_MARKER}: and this one too"

    findings, records = _inspect(line)

    assert len(records) == 1
    assert len(findings) == 1
    assert findings[0].message.startswith(_MARKER)


def test_marker_word_in_prose_is_ignored() -> None:
    """Documentation *about* the gate is not debt."""
    assert _messages(f"# the {_MARKER} gate rejects notes without an owner") == []
    assert _messages(f"# Status: {_MARKER}") == []


def test_prose_trees_and_markdown_are_out_of_scope() -> None:
    """Debt records live beside code, so docs and rule text are not scanned."""
    module = _load_module()

    assert ".md" not in module._EXTENSIONS
    assert ".mdc" not in module._EXTENSIONS
    assert not any("docs" in root for root in module._SCAN_ROOTS)
    assert not any(".cursor/rules" in root for root in module._SCAN_ROOTS)


def test_vendored_and_generated_trees_are_skipped() -> None:
    """Another team's code is not our debt (090), and build output is not editable (017)."""
    module = _load_module()

    for excluded in ("JavaEdms", "edms-ai-assistant", "node_modules", "dist"):
        assert excluded in module._EXCLUDED_PARTS


def test_repository_itself_has_no_malformed_markers() -> None:
    """The artefact the gate protects: this repo must pass its own rule."""
    module = _load_module()

    findings, _ = module.collect()

    assert findings == [], [finding.render() for finding in findings]


def test_stale_records_are_reported_without_blocking(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Age is visible but not fatal by default: a gate would be beaten by a date bump."""
    module = _load_module()
    old = _record("team", _VALID_TICKET, "2020-01-01")
    _, records = module._inspect_line("sample.py", 3, old, date(2020, 1, 1))
    monkeypatch.setattr(module, "collect", lambda today=None: ([], records))

    assert module.main([]) == 0
    assert "stale" in capsys.readouterr().out

    assert module.main(["--fail-on-stale"]) == 1


def test_malformed_markers_block(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The blocking half of the gate: a note without a record fails the run."""
    module = _load_module()
    findings, _ = module._inspect_line("sample.py", 1, _bare(":"), date.today())
    monkeypatch.setattr(module, "collect", lambda today=None: (findings, []))

    assert module.main([]) == 1
    assert "malformed record" in capsys.readouterr().out
