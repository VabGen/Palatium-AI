# src/palatium_ai/application/agents/evals/conflict_linter/sections.py

"""Split prompt prose into ``# HEADER`` blocks for same-section conflict checks."""

from __future__ import annotations

import re

from dataclasses import dataclass
from typing import Final

_HEADER: Final[re.Pattern[str]] = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class PromptSection:
    title: str
    body: str
    start_line: int


def split_sections(text: str) -> list[PromptSection]:
    """Return ``#``-headed sections; leading prose before the first header is ``(preamble)``."""
    matches = list(_HEADER.finditer(text))
    if not matches:
        return [PromptSection(title="(preamble)", body=text, start_line=1)]

    sections: list[PromptSection] = []
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()]
        if preamble.strip():
            sections.append(PromptSection(title="(preamble)", body=preamble, start_line=1))

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end]
        start_line = text.count("\n", 0, match.start()) + 1
        sections.append(PromptSection(title=match.group(1).strip(), body=body, start_line=start_line))
    return sections


def extract_string_literals(source: str) -> list[tuple[str, int]]:
    """Best-effort extraction of triple/single quoted string bodies with start lines.

    Used so we scan prompt *prose*, not Python syntax around it. Imperfect for
    concatenated expressions — callers may also pass already-resolved prompt text.
    """
    pattern = re.compile(
        r'(?P<q>"""|\'\'\'|"|\')(?P<body>.*?)(?P=q)',
        re.DOTALL,
    )
    out: list[tuple[str, int]] = []
    for match in pattern.finditer(source):
        body = match.group("body")
        if len(body) < 40:
            continue
        start_line = source.count("\n", 0, match.start("body")) + 1
        out.append((body, start_line))
    return out
