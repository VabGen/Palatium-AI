"""Session context privacy: preview bound for durable session.context."""

from __future__ import annotations

from palatium_ai.domain.sessions.context_privacy import (
    SESSION_USER_TEXT_PREVIEW_MAX_CHARS,
    session_user_text_preview,
)


def test_preview_keeps_short_text() -> None:
    assert session_user_text_preview("hello") == "hello"


def test_preview_truncates_long_text() -> None:
    long = "x" * (SESSION_USER_TEXT_PREVIEW_MAX_CHARS + 40)
    preview = session_user_text_preview(long)
    assert len(preview) == SESSION_USER_TEXT_PREVIEW_MAX_CHARS
    assert preview.endswith("…")
    assert preview.startswith("x" * (SESSION_USER_TEXT_PREVIEW_MAX_CHARS - 1))


def test_preview_strips_whitespace() -> None:
    assert session_user_text_preview("  hi  ") == "hi"
