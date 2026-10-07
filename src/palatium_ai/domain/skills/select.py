# src/palatium_ai/domain/skills/select.py

"""Select procedural skills from a level-1 catalog by description overlap."""

from __future__ import annotations

import re

from collections.abc import Sequence

_CATALOG_LINE = re.compile(r"^- (?P<name>[a-z0-9][a-z0-9_-]{0,63})(?: \[\+ref\])?: (?P<desc>.+)$")
_TOKEN = re.compile(r"[a-z0-9_]{3,}")


def parse_skill_catalog_entries(catalog_text: str) -> tuple[tuple[str, str], ...]:
    """Parse ``format_catalog`` lines into ``(name, description)`` pairs."""
    entries: list[tuple[str, str]] = []
    for line in catalog_text.splitlines():
        match = _CATALOG_LINE.match(line.strip())
        if match is None:
            continue
        entries.append((match.group("name"), match.group("desc").strip()))
    return tuple(entries)


def select_skills_by_overlap(
    user_text: str,
    entries: Sequence[tuple[str, str]],
    *,
    limit: int = 2,
) -> tuple[str, ...]:
    """Rank catalog entries by token overlap with ``user_text``; return up to ``limit`` names.

    Pure retrieval gate for progressive disclosure (not phrase-list routing, 055).
    Requires at least one overlapping token of length ≥ 4, or two shorter tokens.
    """
    query = _tokens(user_text)
    if not query or limit <= 0:
        return ()
    scored: list[tuple[float, str]] = []
    for name, description in entries:
        desc_tokens = _tokens(description)
        if not desc_tokens:
            continue
        overlap = query & desc_tokens
        if not _overlap_qualifies(overlap):
            continue
        score = len(overlap) / len(desc_tokens)
        scored.append((score, name))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(name for _score, name in scored[:limit])


def _tokens(text: str) -> frozenset[str]:
    return frozenset(_TOKEN.findall(text.lower()))


def _overlap_qualifies(overlap: frozenset[str]) -> bool:
    if any(len(token) >= 4 for token in overlap):
        return True
    return len(overlap) >= 2
