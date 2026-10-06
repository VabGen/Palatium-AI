# src/palatium_ai/domain/attachments/citations.py

"""Derive file/page citation labels from fenced attachment turn text (W2 G03)."""

from __future__ import annotations

import re

from re import Match

# ``attachment:<uuid>:<filename>`` (preferred) or legacy ``attachment:<filename>``.
_SOURCE_RE = re.compile(
    r"<<<UNTRUSTED_TOOL_OUTPUT\s+source=attachment:"
    r"(?:(?P<id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}):)?"
    r"(?P<source>[^\s>]+)",
    re.IGNORECASE,
)
_PAGE_RE = re.compile(r"\[\[page\s+(\d+)\]\]", re.IGNORECASE)
_BARE_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_MAX_REFS = 24
# Long PDFs have dozens of [[page N]] markers; dumping every page as a chip looks
# like retrieval noise and crowds out the filename. Cap per-file page chips.
_MAX_PAGE_CITATIONS_PER_FILE = 5


def citation_refs_from_untrusted_context(untrusted_context: str) -> tuple[str, ...]:
    """Build stable citation labels for DocumentMeta.source_refs.

    Same-named uploads stay distinct via a short id suffix when the fence carries
    ``attachment:<uuid>:<filename>``. Empty when the turn has no attachment fence.
    """
    text = (untrusted_context or "").strip()
    if not text:
        return ()
    refs: list[str] = []
    seen: set[str] = set()
    for match in _SOURCE_RE.finditer(text):
        labels = _labels_for_fence(text, match)
        if _append_unique(refs, seen, labels):
            return tuple(refs)
    return tuple(refs)


def _labels_for_fence(text: str, match: Match[str]) -> tuple[str, ...]:
    filename = (match.group("source") or "").strip()
    if not filename:
        return ()
    file_id = (match.group("id") or "").strip()
    base = f"{filename}#{file_id[:8]}" if file_id else filename
    start = match.end()
    close = text.find("<<<END_UNTRUSTED_TOOL_OUTPUT>>>", start)
    body = text[start:close] if close > start else text[start:]
    pages = sorted({int(page) for page in _PAGE_RE.findall(body) if page.isdigit()})
    if not pages:
        return (base,)
    if len(pages) > _MAX_PAGE_CITATIONS_PER_FILE:
        return (base, f"{base}#p{pages[0]}", f"{base}#p{pages[-1]}")
    return tuple(f"{base}#p{page}" for page in pages)


def _append_unique(refs: list[str], seen: set[str], labels: tuple[str, ...]) -> bool:
    """Append unseen labels. Returns True when the global ref cap is reached."""
    for label in labels:
        if label in seen:
            continue
        seen.add(label)
        refs.append(label)
        if len(refs) >= _MAX_REFS:
            return True
    return False


def sanitize_source_refs(refs: tuple[str, ...]) -> tuple[str, ...]:
    """Drop bare attachment UUIDs; keep filename#id[#pN] citation chips only."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        label = (ref or "").strip()
        if not label or _BARE_UUID_RE.match(label):
            continue
        if label in seen:
            continue
        seen.add(label)
        cleaned.append(label)
    return tuple(cleaned)


__all__ = ["citation_refs_from_untrusted_context", "sanitize_source_refs"]
