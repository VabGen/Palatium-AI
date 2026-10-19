# src/palatium_ai/application/agents/formatter/icon_sanitizer.py

"""Map / strip emoji in Formatter streams; keep <icon name="…"/> for the parser.

SSE preview keeps mapped ``<icon name="…"/>`` tokens so the FE can render
``TokenIcon`` during stream (Path C). Unmapped pictographs are dropped.
Incomplete trailing ``<icon…`` fragments are held across chunks.

LLM slips (``x=`` instead of ``name=``) are normalized to ``name=`` with a warning.
"""

from __future__ import annotations

import re

from typing import cast

from palatium_ai.core.logging import get_logger
from palatium_ai.core.logging.context import turn_id_var
from palatium_ai.domain.content.content_document import ICON_NAME_SET, IconToken

logger = get_logger(__name__)

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

# Accept ``name=`` (canonical) and ``x=`` (LLM slip); always emit ``name=``.
_ICON_TOKEN_RE = re.compile(
    r'<icon\s+(?P<attr>name|x)\s*=\s*"(?P<name>[a-z_]+)"\s*/>',
    re.IGNORECASE,
)
_EMOJI_RE = re.compile(
    "[\U0001f300-\U0001faff\U00002700-\U000027bf\U00002600-\U000026ff\U0000fe0f\U0000200d]+",
    flags=re.UNICODE,
)
# Incomplete ``<icon …`` may be up to ~len('<icon name="settings"/>') chars.
_MAX_EMOJI_TAIL = 4
_MAX_ICON_TAIL = 48
_ICON_OPEN = "<icon"


def normalize_icon_markup(text: str) -> str:
    """Rewrite ``<icon x="…"/>`` → ``<icon name="…"/>``; warn once per slip."""

    def _repl(match: re.Match[str]) -> str:
        attr = match.group("attr").lower()
        name = match.group("name").lower()
        if attr == "x":
            logger.warning(
                "icon_attr_x_normalized",
                icon_name=name,
                turn_id=turn_id_var.get(),
            )
        return f'<icon name="{name}"/>'

    return _ICON_TOKEN_RE.sub(_repl, text)


def split_stream_chunk(chunk: str, tail: str) -> tuple[str, str, str]:
    """Split one SSE chunk into preview text, parse-buffer text, and carry tail.

    Returns ``(preview_text, buffer_text, new_tail)``:
    - buffer: mapped emoji → ``<icon name="…"/>``; unmapped emoji removed
    - preview: emoji removed; complete ``<icon/>`` tokens kept for FE TokenIcon
    - tail: incomplete trailing emoji or ``<icon…`` held for the next chunk
    """
    combined = f"{tail}{chunk}"
    if not combined:
        return "", "", ""

    body, new_tail = _split_incomplete_tail(combined)
    if not body:
        return "", "", new_tail

    buffer_text = _emoji_to_icon_tokens(body)
    # Preview keeps icon tokens (FE → TokenIcon); only unmapped emoji already gone.
    preview_text = buffer_text
    return preview_text, buffer_text, new_tail


def flush_stream_tail(tail: str) -> tuple[str, str]:
    """Flush carry-over at end of stream → ``(preview_text, buffer_text)``."""
    if not tail:
        return "", ""
    buffer_text = _emoji_to_icon_tokens(tail)
    return buffer_text, buffer_text


def strip_icon_tokens(text: str) -> str:
    """Remove ``<icon name|x="…"/>`` tokens (parser / defense-in-depth)."""
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


def count_icon_tokens(text: str) -> int:
    """Count icon tokens (either attribute form) remaining in ``text``."""
    return len(_ICON_TOKEN_RE.findall(normalize_icon_markup(text)))


def _emoji_to_icon_tokens(text: str) -> str:
    if not text:
        return ""
    out = normalize_icon_markup(text)
    for emoji in sorted(EMOJI_TO_ICON.keys(), key=len, reverse=True):
        icon = EMOJI_TO_ICON[emoji]
        out = out.replace(emoji, f'<icon name="{icon}"/>')
    return strip_emoji(out)


def _split_incomplete_tail(text: str) -> tuple[str, str]:
    """Hold trailing incomplete ``<hitl-*…``, emoji or ``<icon…`` across chunks."""
    # HITL first — they are longer and break server-side tag parsing if split.
    hitl_tail = _incomplete_hitl_tail(text)
    if hitl_tail is not None:
        cut = len(text) - len(hitl_tail)
        return text[:cut], hitl_tail

    icon_tail = _incomplete_icon_tail(text)
    if icon_tail is not None:
        cut = len(text) - len(icon_tail)
        return text[:cut], icon_tail

    if len(text) <= _MAX_EMOJI_TAIL and _EMOJI_RE.fullmatch(text):
        return "", text
    n = min(_MAX_EMOJI_TAIL, len(text))
    for k in range(n, 0, -1):
        suffix = text[-k:]
        if _EMOJI_RE.fullmatch(suffix) or suffix.endswith(("\ufe0f", "\u200d")):
            return text[:-k], suffix
    return text, ""


def _incomplete_icon_tail(text: str) -> str | None:
    """Return a trailing incomplete ``<icon…`` fragment, or None if complete / absent."""
    lower = text.lower()
    # Hold a bare prefix of ``<icon`` (e.g. ``<ic``) at end of chunk.
    for n in range(1, len(_ICON_OPEN)):
        if lower.endswith(_ICON_OPEN[:n]):
            return text[-n:]

    idx = lower.rfind(_ICON_OPEN)
    if idx < 0:
        return None
    fragment = text[idx:]
    if len(fragment) > _MAX_ICON_TAIL:
        return None
    # Complete self-closing tag already finished — do not hold.
    if _ICON_TOKEN_RE.search(fragment):
        return None
    # Closed with ``>`` but not ``/>`` — malformed; do not carry forever.
    if re.search(r"(?<!/)>", fragment):
        return None
    return fragment


# ───────────────────── HITL tag tail protection ─────────────────────

_INCOMPLETE_HITL = re.compile(
    r"<hitl-(?:action|choice)\b[^>]*$",
    re.IGNORECASE,
)
_MAX_HITL_TAIL = 512  # hitl-choice with a long options= JSON array


def _incomplete_hitl_tail(text: str) -> str | None:
    """Hold a trailing incomplete ``<hitl-action/>`` / ``<hitl-choice/>`` across chunks."""
    match = _INCOMPLETE_HITL.search(text)
    if match is None:
        return None
    fragment = text[match.start() :]
    if len(fragment) > _MAX_HITL_TAIL:
        return None
    # Already closed with ``>`` or ``/>`` — do not hold.
    if re.search(r"/?>", fragment):
        return None
    return fragment
