"""Session context privacy: bound PII retained outside dialog transcript."""

from __future__ import annotations

# Soft bound for session.context keys (not the authoritative user utterance).
SESSION_USER_TEXT_PREVIEW_MAX_CHARS = 256


def session_user_text_preview(
    text: str,
    *,
    max_chars: int = SESSION_USER_TEXT_PREVIEW_MAX_CHARS,
) -> str:
    """Truncate user text for durable session.context (full text lives in DialogTurnStore)."""
    cleaned = text.strip()
    if max_chars < 1:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned
    if max_chars == 1:
        return "…"
    return f"{cleaned[: max_chars - 1]}…"
