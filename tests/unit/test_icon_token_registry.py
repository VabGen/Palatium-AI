"""IconToken allow-list stays in sync with the UI glyph registry (F1)."""

from __future__ import annotations

import re

from pathlib import Path

from palatium_ai.domain.content.content_document import ICON_NAME_SET, ICON_NAMES


def test_icon_names_closed_and_unique() -> None:
    assert len(ICON_NAMES) == len(ICON_NAME_SET)
    assert len(ICON_NAMES) >= 36


def test_python_icon_tokens_match_typescript_union() -> None:
    ts_path = Path(__file__).resolve().parents[2] / "web" / "src" / "types" / "contentDocument.ts"
    text = ts_path.read_text(encoding="utf-8")
    match = re.search(r"export type IconToken\s*=\s*((?:\|?\s*'[a-z_]+'\s*)+);", text)
    assert match is not None, "IconToken union missing in contentDocument.ts"
    ts_names = tuple(re.findall(r"'([a-z_]+)'", match.group(1)))
    assert tuple(ICON_NAMES) == ts_names


def test_python_icon_tokens_match_kimi_token_glyphs() -> None:
    glyphs_path = Path(__file__).resolve().parents[2] / "web" / "src" / "icons" / "kimiTokenGlyphs.tsx"
    text = glyphs_path.read_text(encoding="utf-8")
    start = text.index("export const KIMI_TOKEN_GLYPHS")
    body = text[start:]
    open_brace = body.index("{")
    depth = 0
    end = None
    for index, char in enumerate(body[open_brace:], start=open_brace):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index
                break
    assert end is not None
    map_body = body[open_brace + 1 : end]
    glyph_keys = tuple(re.findall(r"^\s*([a-z_]+)\s*:", map_body, re.MULTILINE))
    assert tuple(ICON_NAMES) == glyph_keys
