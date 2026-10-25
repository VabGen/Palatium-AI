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

# ``attachment:<uuid>:<filename>`` (preferred) or legacy ``attachment:<filename>``.
_SOURCE_RE = re.compile(
    r"<<<UNTRUSTED_TOOL_OUTPUT\s+source=attachment:"
    r"(?:(?P<id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}):)?"
    r"(?P<source>[^\s>]+)",
    re.IGNORECASE,
)
_UUID_RE = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_BARE_UUID_RE = re.compile(rf"^{_UUID_RE}$")
# LLM often echoes fence sources: ``attachment:<uuid>``, ``attachment:<uuid>:file``,
# or legacy ``attachment:file`` — never show the technical prefix in UI chips.
_ATTACHMENT_PREFIX_RE = re.compile(
    rf"^attachment:(?:(?P<id>{_UUID_RE}):)?(?P<rest>.+)$",
    re.IGNORECASE,
)
_ATTACHMENT_UUID_ONLY_RE = re.compile(rf"^attachment:(?P<id>{_UUID_RE})$", re.IGNORECASE)
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
    labelled = _labelled_fences(untrusted_context)
    if not labelled:
        return ()

    refs: list[str] = []
    seen: set[str] = set()
    for label, _ in labelled:
        if label in seen:
            continue
        seen.add(label)
        refs.append(label)
        if len(refs) >= _MAX_REFS:
            break
    return tuple(refs)


def attachment_ids_by_label(untrusted_context: str) -> dict[str, str]:
    """Map a citation label to the attachment id it names, when it names exactly one.

    The label is built by the same rule that produces the chips, so the chip the user
    clicked and the file that opens cannot disagree. A label that still collects more
    than one id stays out: picking one of two same-named uploads is a guess, and the
    UI then hides "show in source" instead of opening the wrong document (020, 055).
    """
    ids_by_label: dict[str, set[str]] = defaultdict(set)
    for label, attachment_id in _labelled_fences(untrusted_context):
        if attachment_id:
            ids_by_label[label].add(attachment_id)
    return {label: next(iter(ids)) for label, ids in ids_by_label.items() if len(ids) == 1}


def _labelled_fences(untrusted_context: str) -> list[tuple[str, str]]:
    """``(label, full attachment id)`` per fence, first-seen order."""
    entries = _fence_entries(untrusted_context)
    ids_by_name: dict[str, set[str]] = defaultdict(set)
    for filename, attachment_id in entries:
        if attachment_id:
            ids_by_name[filename].add(attachment_id)

    labelled: list[tuple[str, str]] = []
    for filename, attachment_id in entries:
        id8 = attachment_id[:8]
        needs_id = len(ids_by_name[filename]) > 1
        labelled.append((f"{filename}#{id8}" if needs_id and id8 else filename, attachment_id))
    return labelled


def _fence_entries(untrusted_context: str) -> list[tuple[str, str]]:
    """``(filename, full attachment id)`` per fence; the id is empty for legacy fences."""
    text = (untrusted_context or "").strip()
    if not text:
        return []
    entries: list[tuple[str, str]] = []
    for match in _SOURCE_RE.finditer(text):
        filename = (match.group("source") or "").strip()
        if not filename:
            continue
        entries.append((filename, (match.group("id") or "").strip().lower()))
    return entries


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


def _normalize_ref_label(label: str) -> str | None:
    """Strip ``attachment:`` fence echoes; drop uuid-only technical refs."""
    text = label.strip()
    if not text:
        return None
    if _ATTACHMENT_UUID_ONLY_RE.match(text) or _BARE_UUID_RE.match(text):
        return None
    prefixed = _ATTACHMENT_PREFIX_RE.match(text)
    if prefixed is not None:
        rest = (prefixed.group("rest") or "").strip()
        if not rest or _BARE_UUID_RE.match(rest):
            return None
        return rest
    return text


def _parse_ref_parts(label: str) -> tuple[str, str] | None:
    normalized = _normalize_ref_label(label)
    if normalized is None:
        return None
    match = _REF_PARTS_RE.match(normalized)
    if match is None:
        return None
    filename = (match.group("name") or "").strip()
    if not filename or filename.lower().startswith("attachment:"):
        return None
    id8 = (match.group("id") or "").strip().lower()
    return filename, id8


__all__ = ["attachment_ids_by_label", "citation_refs_from_untrusted_context", "sanitize_source_refs"]
