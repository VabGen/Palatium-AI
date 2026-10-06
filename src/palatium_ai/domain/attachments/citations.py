# src/palatium_ai/domain/attachments/citations.py

"""Derive file citation labels from fenced attachment turn text (W2 G03).

User-facing ``source_refs`` chips show filenames only. Internal attachment-id
and page suffixes (``file.pdf#4a742ff9#p1``) stay out of the UI — they look like
duplicate indicators next to clean LLM filenames. Short ``#id8`` is added only
when two same-named uploads must stay distinct.
"""

from __future__ import annotations

import re

from collections import defaultdict
from re import Match

# ``attachment:<uuid>:<filename>`` (preferred) or legacy ``attachment:<filename>``.
_SOURCE_RE = re.compile(
    r"<<<UNTRUSTED_TOOL_OUTPUT\s+source=attachment:"
    r"(?:(?P<id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}):)?"
    r"(?P<source>[^\s>]+)",
    re.IGNORECASE,
)
_BARE_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
# ``name.pdf``, ``name.pdf#aaaaaaaa``, ``name.pdf#aaaaaaaa#p1``, ``name.pdf#p1``.
_REF_PARTS_RE = re.compile(
    r"^(?P<name>.+?)"
    r"(?:#(?P<id>[0-9a-fA-F]{8}))?"
    r"(?:#p(?P<page>\d+))?$",
    re.IGNORECASE,
)
_MAX_REFS = 24


def citation_refs_from_untrusted_context(untrusted_context: str) -> tuple[str, ...]:
    """Build user-facing citation labels for DocumentMeta.source_refs.

    One chip per attachment fence (filename). Same-named uploads stay distinct
    via a short id suffix when the fence carries ``attachment:<uuid>:<filename>``.
    Empty when the turn has no attachment fence.
    """
    text = (untrusted_context or "").strip()
    if not text:
        return ()

    fences: list[tuple[str, str]] = []
    for match in _SOURCE_RE.finditer(text):
        parsed = _fence_filename_and_id(match)
        if parsed is not None:
            fences.append(parsed)
    if not fences:
        return ()

    ids_by_name: dict[str, set[str]] = defaultdict(set)
    for filename, id8 in fences:
        if id8:
            ids_by_name[filename].add(id8)

    refs: list[str] = []
    seen: set[str] = set()
    for filename, id8 in fences:
        needs_id = len(ids_by_name[filename]) > 1
        label = f"{filename}#{id8}" if needs_id and id8 else filename
        if label in seen:
            continue
        seen.add(label)
        refs.append(label)
        if len(refs) >= _MAX_REFS:
            break
    return tuple(refs)


def _fence_filename_and_id(match: Match[str]) -> tuple[str, str] | None:
    filename = (match.group("source") or "").strip()
    if not filename:
        return None
    file_id = (match.group("id") or "").strip()
    return filename, file_id[:8].lower() if file_id else ""


def sanitize_source_refs(refs: tuple[str, ...]) -> tuple[str, ...]:
    """Drop bare UUIDs / page noise; collapse ``file#id#pN`` to user-facing chips.

    Prefer plain filenames. Keep ``filename#id8`` only when the merged set has
    more than one distinct id for the same filename (same-name uploads).
    """
    parsed: list[tuple[str, str]] = []
    for ref in refs:
        label = (ref or "").strip()
        if not label or _BARE_UUID_RE.match(label):
            continue
        parts = _parse_ref_parts(label)
        if parts is None:
            continue
        filename, id8 = parts
        parsed.append((filename, id8))

    if not parsed:
        return ()

    ids_by_name: dict[str, set[str]] = defaultdict(set)
    for filename, id8 in parsed:
        if id8:
            ids_by_name[filename].add(id8)

    cleaned: list[str] = []
    seen: set[str] = set()
    for filename, id8 in parsed:
        needs_id = len(ids_by_name[filename]) > 1
        display = f"{filename}#{id8}" if needs_id and id8 else filename
        if display in seen:
            continue
        seen.add(display)
        cleaned.append(display)
        if len(cleaned) >= _MAX_REFS:
            break
    return tuple(cleaned)


def _parse_ref_parts(label: str) -> tuple[str, str] | None:
    match = _REF_PARTS_RE.match(label)
    if match is None:
        return None
    filename = (match.group("name") or "").strip()
    if not filename:
        return None
    id8 = (match.group("id") or "").strip().lower()
    return filename, id8


__all__ = ["citation_refs_from_untrusted_context", "sanitize_source_refs"]
