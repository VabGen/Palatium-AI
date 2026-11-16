# src/palatium_ai/application/agents/evals/conflict_linter/noqa.py

"""Escape hatch: ``# noqa: conflict-linter — <why>`` (required why after em/en dash or colon)."""

from __future__ import annotations

import re

from typing import Final

#: Line-local suppressions. Why-clause is mandatory so exceptions stay reviewable.
_NOQA_RE: Final[re.Pattern[str]] = re.compile(
    r"#\s*noqa:\s*conflict-linter"
    r"(?:\s*[—\-:]\s*(?P<why>.+))?\s*$",
    re.IGNORECASE,
)


def parse_noqa_reason(line: str) -> str | None:
    """Return why-text when the line suppresses conflict-linter; ``None`` if not a noqa."""
    match = _NOQA_RE.search(line)
    if match is None:
        return None
    why = (match.group("why") or "").strip()
    return why or ""


def noqa_map(source: str) -> dict[int, str]:
    """Map 1-based line numbers → why (empty string if noqa lacks why — still suppresses)."""
    out: dict[int, str] = {}
    for index, line in enumerate(source.splitlines(), start=1):
        parsed = parse_noqa_reason(line)
        if parsed is not None:
            out[index] = parsed
    return out


def nearest_noqa(line_hint: int | None, mapping: dict[int, str], *, window: int = 3) -> str | None:
    """Find a noqa on or near ``line_hint`` (multi-line string findings are approximate)."""
    if line_hint is None:
        return None
    if line_hint in mapping:
        return mapping[line_hint]
    for offset in range(1, window + 1):
        for candidate in (line_hint - offset, line_hint + offset):
            if candidate in mapping:
                return mapping[candidate]
    return None


def count_noqa_markers(source: str) -> int:
    """How many ``conflict-linter`` noqa lines appear in ``source``."""
    return len(noqa_map(source))
