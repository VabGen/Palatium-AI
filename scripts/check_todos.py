#!/usr/bin/env python
"""TODO/FIXME gate (rule 086).

A debt marker is a promise to a *future* reader, so it must say who owes it, where it is
tracked and when it was written. A bare ``# TODO`` note with no owner is not a record — it
is a comment nobody will ever act on, and it is exactly what this gate rejects.

Accepted shape (three non-empty fields, the date last)::

    <MARKER>(owner, ticket, date): what is owed and why it is not done now

* ``owner`` — team/workstream, not a personal name: an individual leaves, the debt stays.
* ``ticket`` — ``#123`` (tracker issue) or a path to a versioned plan/spec
  (``plans/cursor-rules-hardening §5``, resolved against the repo root, then ``.cursor/``).
  A path that does not exist is a dangling reference, so it fails: that is what makes
  this check more than a regex.
* ``date`` — ISO-8601, when the debt was recorded. A future date fails (typo or an
  attempt to postpone the age report below).

Two levels, deliberately:

* **format** — blocking. A marker that is not a record carries no information, and the
  fix is local (write it properly or delete it).
* **age** — reported, not blocking, unless ``--fail-on-stale`` is passed. An age gate
  would be answered by deleting the comment or bumping the date — both strictly worse
  than a visible count (017: do not push a tool's limit onto correct code). The report
  keeps long-lived debt in sight without rewarding silence.

Scope: code and configuration only. Markdown is excluded on purpose — in prose the marker
word is part of documentation (including the rule that documents this format), and debt
records live next to the code they describe.

Usage::

    poetry run python scripts/check_todos.py
    poetry run python scripts/check_todos.py --fail-on-stale
"""

from __future__ import annotations

import argparse
import re
import sys

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

# The marker must *look* like a marker: the word followed by `:` (a bare note) or `(`.
# Prose mentions ("the marker gate", plan checklists, rule text) are therefore ignored —
# otherwise the documentation about this gate would fail it.
_MARKER_RE = re.compile(r"\b(?P<marker>TODO|FIXME|XXX|HACK)(?P<separator>[:(])")

# A complete record: `(owner, ticket, date):`. Fields may not contain `,` or `)`.
_RECORD_RE = re.compile(
    r"\b(?:TODO|FIXME|XXX|HACK)"
    r"\(\s*(?P<owner>[^,()]+?)\s*,\s*(?P<ticket>[^,()]+?)\s*,\s*(?P<day>\d{4}-\d{2}-\d{2})\s*\)\s*:"
)

# Tracker reference: the only ticket form that cannot be verified offline.
_ISSUE_RE = re.compile(r"#\d+")
# Path-shaped token inside a ticket: it must contain a separator, so a bare word
# ("later", "someday") cannot pass as a reference. Verifiable, and the reason a dangling
# plan reference does not silently pass.
_PATH_TOKEN_RE = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+")
# Extensions tried when a ticket names a document without one (`plans/<file> §N`).
_IMPLIED_SUFFIXES: tuple[str, ...] = ("", ".md")

# Roots scanned for markers. Prose trees (`docs/`, `.cursor/rules|plans|skills/`) are absent
# by design; `web/` and `mcp_servers/` are in because their code ships.
_SCAN_ROOTS: tuple[str, ...] = (
    "src",
    "tests",
    "scripts",
    "alembic",
    "mcp_servers",
    "deploy",
    "security",
    "web",
    ".github/workflows",
    ".cursor/hooks",
)
# Root-level manifests with no extension worth keying on.
_SCAN_FILES: tuple[str, ...] = (
    "Dockerfile",
    "Makefile",
)
_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".mjs",
        ".cjs",
        ".sh",
        ".ps1",
        ".yml",
        ".yaml",
        ".toml",
        ".ini",
        ".cfg",
        ".sql",
        ".css",
        ".html",
    }
)
# Vendored/generated/derived trees: not ours to annotate (017, 090), plus build outputs.
_EXCLUDED_PARTS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "dist",
        "dist-widget",
        "artifacts",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".shots",
        "test-results",
        "playwright-report",
        # Read-only references owned by other teams (090): editing them is out of scope,
        # so their markers are not our debt.
        "JavaEdms",
        "edms-ai-assistant",
    }
)


@dataclass(frozen=True)
class Finding:
    """A blocking format violation or a non-blocking stale record."""

    path: str
    line: int
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


@dataclass(frozen=True)
class Record:
    """A well-formed debt record, kept so age can be reported."""

    path: str
    line: int
    owner: str
    ticket: str
    day: date


def _iter_source_files() -> list[Path]:
    """Every scannable file, deduplicated and in stable order."""
    found: set[Path] = set()
    for root in _SCAN_ROOTS:
        base = _ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or _is_excluded(path):
                continue
            if path.suffix.lower() in _EXTENSIONS:
                found.add(path)
    for name in _SCAN_FILES:
        path = _ROOT / name
        if path.is_file():
            found.add(path)
    return sorted(found)


def _is_excluded(path: Path) -> bool:
    return any(part in _EXCLUDED_PARTS for part in path.relative_to(_ROOT).parts)


def _resolve_ticket(ticket: str) -> str | None:
    """Return a problem description for an unverifiable ticket, or ``None`` if fine."""
    if _ISSUE_RE.search(ticket):
        return None
    tokens = _PATH_TOKEN_RE.findall(ticket)
    if not tokens:
        return "ticket must be #<issue> or a path to a versioned plan/spec (e.g. plans/<file> §N)"
    for token in tokens:
        # Trailing punctuation from the sentence ("…§5.") is not part of the path.
        cleaned = token.rstrip(".-")
        candidates = [
            base / f"{cleaned}{suffix}" for base in (_ROOT, _ROOT / ".cursor") for suffix in _IMPLIED_SUFFIXES
        ]
        if not any(candidate.is_file() for candidate in candidates):
            return f"ticket references {cleaned!r}, which does not exist in this repo"
    return None


def _today() -> date:
    """Today in UTC.

    ``date.today()`` reads the machine's zone, so a debt recorded near midnight would flip
    the age and "future date" verdicts between CI and a laptop (010).
    """
    return datetime.now(UTC).date()


def _inspect_line(rel_path: str, line_no: int, line: str, today: date) -> tuple[list[Finding], list[Record]]:
    findings: list[Finding] = []
    records: list[Record] = []

    for match in _RECORD_RE.finditer(line):
        owner = match.group("owner").strip()
        ticket = match.group("ticket").strip()
        raw_day = match.group("day")
        try:
            recorded = date.fromisoformat(raw_day)
        except ValueError:
            findings.append(Finding(rel_path, line_no, f"date {raw_day!r} is not a valid ISO-8601 date"))
            continue
        if recorded > today:
            findings.append(Finding(rel_path, line_no, f"date {raw_day} is in the future"))
            continue
        if not owner:
            findings.append(Finding(rel_path, line_no, "owner is empty"))
            continue
        problem = _resolve_ticket(ticket)
        if problem is not None:
            findings.append(Finding(rel_path, line_no, problem))
            continue
        records.append(Record(rel_path, line_no, owner, ticket, recorded))

    # Markers left over once well-formed records are removed: a bare note, not a record.
    remainder = _RECORD_RE.sub("", line)
    findings.extend(
        Finding(rel_path, line_no, f"{match.group('marker')} without (owner, ticket, date) - see rule 086")
        for match in _MARKER_RE.finditer(remainder)
    )
    return findings, records


def collect(today: date | None = None) -> tuple[list[Finding], list[Record]]:
    """Scan the configured scope; return blocking findings and well-formed records."""
    reference_day = today or _today()
    findings: list[Finding] = []
    records: list[Record] = []
    for path in _iter_source_files():
        rel_path = path.relative_to(_ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary-ish content under an extension we scan: nothing to annotate
        for line_no, line in enumerate(text.splitlines(), start=1):
            line_findings, line_records = _inspect_line(rel_path, line_no, line, reference_day)
            findings.extend(line_findings)
            records.extend(line_records)
    return findings, records


def main(argv: list[str] | None = None) -> int:
    """Run the marker gate; non-zero only on format violations (or with ``--fail-on-stale``)."""
    parser = argparse.ArgumentParser(description="TODO/FIXME record gate (rule 086)")
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=180,
        help="age above which a record is reported as stale (default: 180)",
    )
    parser.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="treat stale records as blocking (off by default: reporting beats deleting)",
    )
    args = parser.parse_args(argv)

    today = _today()
    findings, records = collect(today)
    stale = [record for record in records if (today - record.day).days > args.max_age_days]

    print("== debt markers (086) ==")
    for finding in findings:
        print(f"  {finding.render()}")
    for record in stale:
        age = (today - record.day).days
        print(f"  stale ({age}d): {record.path}:{record.line}: {record.owner} · {record.ticket}")

    if findings:
        print(f"debt markers: {len(findings)} malformed record(s) - blocking")
        return 1

    print(f"debt markers: {len(records)} record(s) ok, {len(stale)} stale (>{args.max_age_days}d)")
    if stale and args.fail_on_stale:
        print("debt markers: stale records are blocking (--fail-on-stale)")
        return 1
    print("check_todos: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
