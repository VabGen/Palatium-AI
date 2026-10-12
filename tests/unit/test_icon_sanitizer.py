"""Icon sanitizer: emoji → tokens in buffer; preview stripped; tail carry."""

from __future__ import annotations

from palatium_ai.application.agents.formatter.icon_sanitizer import (
    flush_stream_tail,
    normalize_icon_markup,
    sanitize_markdown_buffer,
    split_stream_chunk,
    strip_emoji,
    strip_icon_tokens,
)


def test_mapped_emoji_becomes_icon_token_in_buffer() -> None:
    preview, buffered, tail = split_stream_chunk("Hello 📄 world", "")
    assert tail == ""
    assert '<icon name="document"/>' in buffered
    assert "📄" not in buffered
    assert "📄" not in preview
    assert "<icon" not in preview
    assert "Hello" in preview
    assert "world" in preview


def test_unmapped_emoji_stripped_from_both() -> None:
    preview, buffered, _tail = split_stream_chunk("Call 📞 now", "")
    assert "📞" not in preview
    assert "📞" not in buffered
    assert "<icon" not in buffered
    assert "Call" in preview
    assert "now" in preview


def test_preview_strips_existing_icon_tokens() -> None:
    preview, buffered, _ = split_stream_chunk('<icon name="warning"/> Alert', "")
    assert buffered.startswith('<icon name="warning"/>')
    assert "<icon" not in preview
    assert "Alert" in preview


def test_surrogate_pair_held_across_chunks() -> None:
    # Split a multi-codepoint emoji so the first chunk ends mid-sequence.
    emoji = "⚠️"
    assert len(emoji) >= 2
    _p0, b0, tail = split_stream_chunk(emoji[0], "")
    assert b0 == ""
    assert tail == emoji[0]
    preview, buffered, tail2 = split_stream_chunk(emoji[1:] + " ok", tail)
    assert tail2 == ""
    assert '<icon name="warning"/>' in buffered
    assert "ok" in preview
    assert "⚠" not in preview
    assert "⚠️" not in buffered


def test_flush_stream_tail_maps_emoji() -> None:
    preview, buffered = flush_stream_tail("📋")
    assert '<icon name="document"/>' in buffered
    assert preview == ""
    assert strip_icon_tokens(buffered) == ""


def test_sanitize_markdown_buffer_one_shot() -> None:
    out = sanitize_markdown_buffer("Risk ⚠️ ahead ✅")
    assert '<icon name="warning"/>' in out
    assert '<icon name="check"/>' in out
    assert "⚠" not in out
    assert "✅" not in out


def test_strip_emoji_defense() -> None:
    cleaned = strip_emoji("x ✅ y")
    assert "✅" not in cleaned
    assert "x" in cleaned
    assert "y" in cleaned


def test_normalize_icon_markup_rewrites_x_attr() -> None:
    out = normalize_icon_markup('<icon x="check"/> done')
    assert out == '<icon name="check"/> done'
    assert strip_icon_tokens(out) == " done"


def test_split_stream_accepts_x_attr_in_buffer() -> None:
    preview, buffered, _ = split_stream_chunk('<icon x="document"/> Report', "")
    assert '<icon name="document"/>' in buffered
    assert "<icon" not in preview
    assert "Report" in preview
