# src/palatium_ai/application/agents/formatter/icon_sanitizer.py

"""Map / strip emoji in Formatter streams; keep <icon name="…"/> for the parser.

SSE preview must never show emoji or icon tokens. The parse buffer keeps mapped
``<icon name="…"/>`` tokens and drops unmapped pictographs.
"""

from __future__ import annotations

import re

from typing import cast

from palatium_ai.domain.content.content_document import ICON_NAME_SET, IconToken

# Longest-first replacement order so composite pictographs win over single points.
EMOJI_TO_ICON: dict[str, IconToken] = {
    "⚠️": "warning",
    "⚠": "warning",
    "🛑": "danger",
    "⛔": "danger",
    "\u2139\ufe0f": "info",  # information source + VS16
    "\u2139": "info",
    "✅": "check",
    "❌": "x",
    "✓": "check",
    "📄": "document",
    "📃": "document",
    "📋": "document",
    "👤": "user",
    "🧑": "user",
    "👥": "users",
    "⏰": "clock",
    "🕐": "clock",
    "📊": "chart",
    "💰": "chart",
    "⚙️": "settings",
    "⚙": "settings",
    "✨": "success",
    "🎉": "success",
}

_ICON_TOKEN_RE = re.compile(r'<icon\s+name="([a-z_]+)"\s*/>', re.IGNORECASE)
_EMOJI_RE = re.compile(
    "[\U0001f300-\U0001faff\U00002700-\U000027bf\U00002600-\U000026ff\U0000fe0f\U0000200d]+",
    flags=re.UNICODE,
)
_MAX_TAIL = 4


def split_stream_chunk(chunk: str, tail: str) -> tuple[str, str, str]:
    """Split one SSE chunk into preview text, parse-buffer text, and carry tail.

    Returns ``(preview_text, buffer_text, new_tail)``:
    - buffer: mapped emoji → ``<icon name="…"/>``; unmapped emoji removed
    - preview: emoji and ``<icon/>`` tokens removed
    - tail: incomplete trailing sequence (≤4 chars) held for the next chunk
    """
    combined = f"{tail}{chunk}"
    if not combined:
        return "", "", ""

    body, new_tail = _split_incomplete_tail(combined)
    if not body:
        return "", "", new_tail

    buffer_text = _emoji_to_icon_tokens(body)
    preview_text = strip_icon_tokens(buffer_text)
    return preview_text, buffer_text, new_tail


def flush_stream_tail(tail: str) -> tuple[str, str]:
    """Flush carry-over at end of stream → ``(preview_text, buffer_text)``."""
    if not tail:
        return "", ""
    buffer_text = _emoji_to_icon_tokens(tail)
    return strip_icon_tokens(buffer_text), buffer_text


def strip_icon_tokens(text: str) -> str:
    """Remove ``<icon name="…"/>`` tokens (preview / defense-in-depth)."""
    return _ICON_TOKEN_RE.sub("", text)


def strip_emoji(text: str) -> str:
    """Remove remaining pictographs from document text fields."""
    return _EMOJI_RE.sub("", text)


def coerce_icon_name(raw: str) -> IconToken | None:
    """Return a valid IconToken or None if ``raw`` is outside the allow-list."""
    name = raw.strip().lower()
    if name not in ICON_NAME_SET:
        return None
    return cast("IconToken", name)


def sanitize_markdown_buffer(text: str) -> str:
    """Map emoji → icon tokens and drop unmapped pictographs (post-stream / one-shot)."""
    return _emoji_to_icon_tokens(text)


def _emoji_to_icon_tokens(text: str) -> str:
    if not text:
        return ""
    out = text
    for emoji in sorted(EMOJI_TO_ICON.keys(), key=len, reverse=True):
        icon = EMOJI_TO_ICON[emoji]
        out = out.replace(emoji, f'<icon name="{icon}"/>')
    return strip_emoji(out)


def _split_incomplete_tail(text: str) -> tuple[str, str]:
    """Hold a short trailing emoji/VS/ZWJ run so multi-codepoint glyphs are not split."""
    if len(text) <= _MAX_TAIL and _EMOJI_RE.fullmatch(text):
        return "", text
    n = min(_MAX_TAIL, len(text))
    for k in range(n, 0, -1):
        suffix = text[-k:]
        if _EMOJI_RE.fullmatch(suffix) or suffix.endswith(("\ufe0f", "\u200d")):
            return text[:-k], suffix
    return text, ""
