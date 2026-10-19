# src/palatium_ai/core/observability/file_reread_rollout.py

"""Sticky per-user rollout for the thread file re-read path (055, 070).

``ATTACHMENTS_FILE_REREAD_PCT`` selects coverage of the new tool-dispatch path
(``platform.read_attachment`` on a follow-up turn). Same one-key semantics as the
Formatter contract rollout (``formatter_rollout.py``), so the canary ramp and the
rollback need no deploy:

    0   → off for every caller (dark default; the one-variable rollback)
    5   → sticky ~5% of users (canary)
    100 → every caller (full cutover)

Sticky per user: replicas are never mixed by hand, so a rolling update cannot flip
a dialog onto the re-read path mid-conversation.
"""

from __future__ import annotations

from palatium_ai.core.config import get_settings
from palatium_ai.core.observability.redaction import hash8


def resolve_file_reread(pct: int, user_id: str | None) -> bool:
    """Return whether this caller is inside the re-read cohort (pure; no I/O)."""
    coverage = int(pct)
    if coverage <= 0:
        return False
    if coverage >= 100:
        return True
    bucket = int(hash8((user_id or "").strip() or "anonymous"), 16) % 100
    return bucket < coverage


def is_file_reread_enabled(user_id: str | None = None) -> bool:
    """Effective gate for the re-read path (reads ``ATTACHMENTS_FILE_REREAD_PCT``)."""
    return resolve_file_reread(get_settings().attachments.file_reread_pct, user_id)


__all__ = ["is_file_reread_enabled", "resolve_file_reread"]
