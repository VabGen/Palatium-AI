# src/palatium_ai/domain/attachments/fence_source.py

"""Stable unique fence labels for attachment turn context (020, 065).

Filename alone is not unique: users often upload two near-identical names
(``Кодекс_…_V2.docx`` twice). Without an id in the fence header, citations and
the LLM collapse both into one file and invent a missing second document.
"""

from __future__ import annotations

from uuid import UUID

# Matches ``wrap_untrusted_tool_output`` source cap (tool_output.py).
_SOURCE_MAX = 128
_PREFIX = "attachment:"


def attachment_fence_source(*, attachment_id: UUID, filename: str) -> str:
    """Return ``attachment:<uuid>:<filename>`` truncated to the fence source cap."""
    name = (filename or "").strip() or "file"
    raw = f"{_PREFIX}{attachment_id}:{name}"
    if len(raw) <= _SOURCE_MAX:
        return raw
    # Keep uuid + prefix; truncate the display name (extension stays when possible).
    head = f"{_PREFIX}{attachment_id}:"
    room = _SOURCE_MAX - len(head)
    if room < 1:
        return head[:_SOURCE_MAX]
    if "." in name and len(name.rsplit(".", 1)[-1]) < room:
        stem, ext = name.rsplit(".", 1)
        keep = max(1, room - len(ext) - 1)
        return f"{head}{stem[:keep]}.{ext}"
    return f"{head}{name[:room]}"


__all__ = ["attachment_fence_source"]
