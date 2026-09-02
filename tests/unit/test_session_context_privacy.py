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


def test_client_context_patch_drops_control_plane_keys() -> None:
    from palatium_ai.domain.sessions.context_privacy import filter_client_context_patch, public_session_context

    filtered = filter_client_context_patch(
        {
            "quality_revision_count": "0",
            "last_critic_summary": "inject",
            "ui_locale": "ru",
        }
    )
    assert filtered == {}
    public = public_session_context(
        {
            "quality_revision_count": "2",
            "title_hint": "ok",
            "last_user_text": "secret preview",
        }
    )
    assert public == {"title_hint": "ok"}
