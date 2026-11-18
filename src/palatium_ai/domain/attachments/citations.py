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


def attachment_ids_from_untrusted_context(untrusted_context: str) -> tuple[str, ...]:
    """Ordered unique attachment UUIDs from fence ``source=attachment:<uuid>:…`` headers.

    Used by Researcher JIT re-read when the turn already carries truncated/NOTICE
    fences: identity is in the fence itself, so we must not wait for a name-based
    thread resolver (Context Circulation 2026, 055/070).
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for _filename, attachment_id in _fence_entries(untrusted_context):
        aid = (attachment_id or "").strip().lower()
        if not aid or aid in seen:
            continue
        seen.add(aid)
        ordered.append(aid)
        if len(ordered) >= _MAX_REFS:
            break
    return tuple(ordered)


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


_MD_FILE_WRAP_RE = re.compile(r"^\[([^\]]+)\](?:\([^)]*\))?$")
_WRAP_OPEN = frozenset("[「『\"'«")
_WRAP_CLOSE = frozenset("]」』\"'»")


def _strip_source_ref_decorators(label: str) -> str:
    """Collapse ``[Скан 1.pdf]`` / ``[file](…)`` to the bare basename."""
    text = label.strip()
    md = _MD_FILE_WRAP_RE.match(text)
    if md is not None:
        text = (md.group(1) or "").strip()
    while len(text) >= 2 and text[0] in _WRAP_OPEN and text[-1] in _WRAP_CLOSE:
        text = text[1:-1].strip()
    return text


def _source_ref_fingerprint(name: str) -> str:
    """One chip key for ``Договор_a.docx`` vs ``Договор a.docx`` / ``[file.pdf]``."""
    text = _strip_source_ref_decorators(name)
    if not text:
        return ""
    if text.lower().startswith(("http://", "https://")):
        return text.lower()
    return re.sub(r"[_\s]+", " ", text.lower())


def _prefer_source_ref_label(current: str, candidate: str) -> str:
    """Prefer filesystem basenames (underscores) over spaced prose titles."""

    def _score(value: str) -> int:
        return (2 if "_" in value else 0) + (0 if any(ch.isspace() for ch in value) else 1)

    return candidate if _score(candidate) > _score(current) else current


def sanitize_source_refs(refs: tuple[str, ...]) -> tuple[str, ...]:
    """Drop bare UUIDs / page noise; collapse ``file#id#pN`` to user-facing chips.

    Prefer plain filenames. Keep ``filename#id8`` only when the merged set has
    more than one distinct id for the same file fingerprint (same-name uploads).
    Space↔underscore aliases of one basename collapse to a single chip.
    """
    parsed = _collect_parsed_source_refs(refs)
    if not parsed:
        return ()
    return _collapse_parsed_source_refs(parsed)


def _collect_parsed_source_refs(refs: tuple[str, ...]) -> list[tuple[str, str, str]]:
    """``(filename, id8, fingerprint)`` for each usable ref."""
    parsed: list[tuple[str, str, str]] = []
    for ref in refs:
        label = (ref or "").strip()
        if not label or _BARE_UUID_RE.match(label):
            continue
        parts = _parse_ref_parts(label)
        if parts is None:
            continue
        filename, id8 = parts
        fingerprint = _source_ref_fingerprint(filename)
        if not fingerprint:
            continue
        parsed.append((filename, id8, fingerprint))
    return parsed


def _collapse_parsed_source_refs(parsed: list[tuple[str, str, str]]) -> tuple[str, ...]:
    """Merge aliases and emit at most one chip per fingerprint (or per id when colliding)."""
    preferred: dict[str, str] = {}
    ids_by_fp: dict[str, set[str]] = defaultdict(set)
    for filename, id8, fingerprint in parsed:
        preferred[fingerprint] = _prefer_source_ref_label(preferred.get(fingerprint, filename), filename)
        if id8:
            ids_by_fp[fingerprint].add(id8)

    cleaned: list[str] = []
    seen: set[str] = set()
    for _filename, id8, fingerprint in parsed:
        name = preferred[fingerprint]
        needs_id = len(ids_by_fp[fingerprint]) > 1
        if needs_id:
            if not id8:
                continue
            display = f"{name}#{id8}"
            if display in seen:
                continue
            seen.add(display)
            cleaned.append(display)
        else:
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            cleaned.append(name)
        if len(cleaned) >= _MAX_REFS:
            break
    return tuple(cleaned)


def _normalize_ref_label(label: str) -> str | None:
    """Strip ``attachment:`` fence echoes / ``[file]`` wraps; drop uuid-only refs."""
    text = _strip_source_ref_decorators(label)
    if not text:
        return None
    if _ATTACHMENT_UUID_ONLY_RE.match(text) or _BARE_UUID_RE.match(text):
        return None
    prefixed = _ATTACHMENT_PREFIX_RE.match(text)
    if prefixed is not None:
        rest = _strip_source_ref_decorators((prefixed.group("rest") or "").strip())
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


__all__ = [
    "attachment_ids_by_label",
    "attachment_ids_from_untrusted_context",
    "citation_refs_from_untrusted_context",
    "sanitize_source_refs",
]
