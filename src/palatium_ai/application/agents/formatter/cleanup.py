# src/palatium_ai/application/agents/formatter/cleanup.py

"""Mechanical prose cleanup before Formatter LLM (no icons/sections/style).

Presentation belongs to the LLM path. This module only normalizes whitespace
and fences so the model receives clean input.
"""

from __future__ import annotations

import re

_MULTI_BLANK = re.compile(r"\n{3,}")


def mechanical_cleanup(text: str) -> str:
    """Strip trailing whitespace, normalize newlines, collapse blanks, close fences."""
    if not text:
        return text
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.splitlines()]
    body = _MULTI_BLANK.sub("\n\n", "\n".join(lines)).strip()
    fence_opens = sum(1 for line in body.splitlines() if line.lstrip().startswith("```"))
    if fence_opens % 2 == 1:
        body = f"{body}\n```"
    return body
