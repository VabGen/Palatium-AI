# src/palatium_ai/domain/content/markdown_blocks.py

"""Deterministic prose → ContentBlock conversion (no LLM, 055).

Parses structural markers only: ATX headings, fenced code, ordered/bullet lists,
paragraphs. Language-specific code heuristics (e.g. ``def `` / ``import ``) are
forbidden — fences must be explicit.

Ordered/bullet lists stay open across blank lines and body paragraphs until the
next marker, heading, fence, or EOF (researcher thesis dumps must not become
many one-item ``<ol>`` blocks that each restart at 1).
"""

from __future__ import annotations

import re

from dataclasses import dataclass, field

from palatium_ai.domain.content.content_document import (
    CodeBlock,
    ContentBlock,
    HeadingBlock,
    HeadingLevel,
    ListBlock,
    ListItem,
    ParagraphBlock,
)

_ORDERED_EMPHASIS_MD = re.compile(r"^\s*\d+[.)]\s+\*\*(.+?)\*\*\s*[:—–-]?\s*(.*)$")
_ORDERED_EMPHASIS_PLAIN = re.compile(r"^\s*\d+[.)]\s+([^:\n]{1,80}?):\s+(.+)$")
_ORDERED_PLAIN = re.compile(r"^\s*\d+[.)]\s+(.+)$")
_BULLET_EMPHASIS_MD = re.compile(r"^\s*[-*•]\s+\*\*(.+?)\*\*\s*[:—–-]?\s*(.*)$")
_BULLET_PLAIN = re.compile(r"^\s*[-*•]\s+(.+)$")
_MARKDOWN_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ATX_HEADING = re.compile(r"^\s*(#{1,3})\s+(.+?)\s*#*\s*$")
_FENCE_OPEN = re.compile(r"^\s*```([\w+-]*)\s*$")
_DEFAULT_PARAGRAPH_MAX = 8_000
_LIST_ITEM_TEXT_MAX = 2_000


def prose_to_blocks(
    text: str,
    *,
    max_paragraph_chars: int = _DEFAULT_PARAGRAPH_MAX,
) -> tuple[str | None, tuple[ContentBlock, ...]]:
    """Convert plain / near-markdown prose into optional title + typed blocks.

    Returns ``(title, blocks)``. Title is a short colon-terminated first line
    when present; otherwise ``None``. Always returns at least one block.
    """
    stripped = text.strip() or " "
    title, blocks = _structure_source(stripped, max_paragraph_chars=max_paragraph_chars)
    if not blocks:
        blocks = _paragraph_chunks(stripped, max_chars=max_paragraph_chars)
    return title, tuple(blocks)


def plain_paragraph_count(text: str) -> int | None:
    """Paragraph count when ``text`` is structure-free prose; ``None`` if it has structure.

    Structure = title line, heading, list, or fence — anything the deterministic
    parser would not emit as a plain paragraph.
    """
    title, blocks = prose_to_blocks(text)
    if title is not None or any(block.type != "paragraph" for block in blocks):
        return None
    return len(blocks)


def count_ordered_markers(text: str) -> int:
    """How many top-level ordered-list markers appear (structural packaging signal)."""
    return sum(1 for line in text.splitlines() if _parse_ordered_line(line.strip()) is not None)


@dataclass
class _ParseState:
    """Mutable accumulator while scanning source lines into blocks."""

    title: str | None = None
    blocks: list[ContentBlock] = field(default_factory=list)
    pending_paras: list[str] = field(default_factory=list)
    ordered_items: list[ListItem] = field(default_factory=list)
    bullet_items: list[ListItem] = field(default_factory=list)
    # Body lines buffered while a list is open; absorbed into the previous item
    # when the next marker arrives, otherwise emitted as paragraphs after the list.
    list_trailing: list[str] = field(default_factory=list)
    in_fence: bool = False
    fence_lang: str = "text"
    fence_lines: list[str] = field(default_factory=list)

    def flush_paras(self, *, max_chars: int) -> None:
        for chunk in self.pending_paras:
            self.blocks.extend(_paragraph_chunks(chunk, max_chars=max_chars))
        self.pending_paras = []

    def flush_ordered(self, *, absorb_trailing: bool) -> None:
        if absorb_trailing and self.list_trailing and self.ordered_items:
            self.ordered_items[-1] = _append_item_text(
                self.ordered_items[-1],
                self.list_trailing,
            )
            self.list_trailing = []
        if self.ordered_items:
            self.blocks.append(ListBlock(type="list", style="ordered", items=tuple(self.ordered_items)))
            self.ordered_items = []

    def flush_bullets(self, *, absorb_trailing: bool) -> None:
        if absorb_trailing and self.list_trailing and self.bullet_items:
            self.bullet_items[-1] = _append_item_text(
                self.bullet_items[-1],
                self.list_trailing,
            )
            self.list_trailing = []
        if self.bullet_items:
            self.blocks.append(ListBlock(type="list", style="unordered", items=tuple(self.bullet_items)))
            self.bullet_items = []

    def flush_list_trailing_as_paras(self, *, max_chars: int) -> None:
        if not self.list_trailing:
            return
        joined = "\n\n".join(self.list_trailing).strip()
        self.list_trailing = []
        if joined:
            self.blocks.extend(_paragraph_chunks(joined, max_chars=max_chars))

    def flush_fence(self) -> None:
        if not self.in_fence:
            return
        content = "\n".join(self.fence_lines).strip() or " "
        lang = (self.fence_lang or "text")[:40] or "text"
        self.blocks.append(CodeBlock(type="code", language=lang, content=content[:50_000]))
        self.in_fence = False
        self.fence_lang = "text"
        self.fence_lines = []

    def flush_open(self, *, max_chars: int) -> None:
        """End of section / EOF: close lists without absorbing trailing into items."""
        self.flush_ordered(absorb_trailing=False)
        self.flush_bullets(absorb_trailing=False)
        self.flush_list_trailing_as_paras(max_chars=max_chars)
        self.flush_paras(max_chars=max_chars)


def _structure_source(
    text: str,
    *,
    max_paragraph_chars: int,
) -> tuple[str | None, list[ContentBlock]]:
    if "\n" not in text and not text.lstrip().startswith(("#", "```")):
        return None, _paragraph_chunks(text, max_chars=max_paragraph_chars)

    state = _ParseState()
    for raw in text.splitlines():
        _consume_line(state, raw, max_chars=max_paragraph_chars)
    if state.in_fence:
        state.flush_fence()
    state.flush_open(max_chars=max_paragraph_chars)

    if not state.blocks:
        return state.title, _paragraph_chunks(text, max_chars=max_paragraph_chars)
    return state.title, _maybe_promote_heading(state.title, state.blocks)


def _consume_line(state: _ParseState, raw: str, *, max_chars: int) -> None:
    if state.in_fence:
        _consume_fence_body(state, raw)
        return
    if _try_open_fence(state, raw, max_chars=max_chars):
        return

    line = raw.strip()
    indent = _indent_width(raw)
    if not line:
        _consume_blank(state, max_chars=max_chars)
        return

    heading = _parse_atx_heading(line)
    if heading is not None:
        state.flush_open(max_chars=max_chars)
        state.blocks.append(heading)
        return

    ordered_item = _parse_ordered_line(line)
    if ordered_item is not None:
        _push_ordered_item(state, ordered_item, max_chars=max_chars)
        return

    bullet_item = _parse_bullet_line(line)
    if bullet_item is not None:
        _push_bullet_item(state, _flatten_nested_bullet(bullet_item, indent), max_chars=max_chars)
        return

    _consume_prose(state, line)


def _consume_fence_body(state: _ParseState, raw: str) -> None:
    if raw.strip().startswith("```"):
        state.flush_fence()
        return
    state.fence_lines.append(raw)


def _try_open_fence(state: _ParseState, raw: str, *, max_chars: int) -> bool:
    fence = _FENCE_OPEN.match(raw)
    if fence is None:
        return False
    state.flush_open(max_chars=max_chars)
    state.in_fence = True
    state.fence_lang = (fence.group(1) or "text").strip() or "text"
    state.fence_lines = []
    return True


def _consume_blank(state: _ParseState, *, max_chars: int) -> None:
    # Loose lists: blank lines do not close an open list (CommonMark-ish).
    if state.ordered_items or state.bullet_items:
        return
    state.flush_paras(max_chars=max_chars)


def _push_ordered_item(state: _ParseState, item: ListItem, *, max_chars: int) -> None:
    if state.bullet_items:
        state.flush_bullets(absorb_trailing=False)
        state.flush_list_trailing_as_paras(max_chars=max_chars)
    if state.ordered_items and state.list_trailing:
        state.ordered_items[-1] = _append_item_text(state.ordered_items[-1], state.list_trailing)
        state.list_trailing = []
    state.flush_paras(max_chars=max_chars)
    state.ordered_items.append(item)


def _push_bullet_item(state: _ParseState, item: ListItem, *, max_chars: int) -> None:
    if state.ordered_items:
        state.flush_ordered(absorb_trailing=False)
        state.flush_list_trailing_as_paras(max_chars=max_chars)
    if state.bullet_items and state.list_trailing:
        state.bullet_items[-1] = _append_item_text(state.bullet_items[-1], state.list_trailing)
        state.list_trailing = []
    state.flush_paras(max_chars=max_chars)
    state.bullet_items.append(item)


def _consume_prose(state: _ParseState, line: str) -> None:
    cleaned = _strip_markdown_bold(line)
    if state.ordered_items or state.bullet_items:
        # Defer: absorb into previous item if another marker follows; else paragraph after list.
        state.list_trailing.append(cleaned)
        return
    if _try_set_title(state, cleaned):
        return
    state.pending_paras.append(cleaned)


def _append_item_text(item: ListItem, trailing: list[str]) -> ListItem:
    extra = "\n\n".join(part for part in trailing if part.strip()).strip()
    if not extra:
        return item
    merged = f"{item.text}\n\n{extra}".strip()
    if len(merged) > _LIST_ITEM_TEXT_MAX:
        merged = merged[: _LIST_ITEM_TEXT_MAX - 1].rstrip() + "…"
    return ListItem(text=merged or item.text, emphasis=item.emphasis, icon=item.icon)


def _parse_atx_heading(line: str) -> HeadingBlock | None:
    match = _ATX_HEADING.match(line)
    if match is None:
        return None
    level = min(len(match.group(1)), 3)
    text = _strip_markdown_bold(match.group(2))[:500]
    if not text:
        return None
    heading_level: HeadingLevel = 1 if level == 1 else 2 if level == 2 else 3
    return HeadingBlock(type="heading", level=heading_level, text=text)


def _try_set_title(state: _ParseState, cleaned: str) -> bool:
    """First short colon-terminated line becomes document title."""
    if state.title is not None or state.blocks or state.pending_paras:
        return False
    if not cleaned.endswith(":") or len(cleaned) > 160:
        return False
    state.title = cleaned.rstrip(":").strip()[:200] or None
    return True


def _maybe_promote_heading(
    title: str | None,
    blocks: list[ContentBlock],
) -> list[ContentBlock]:
    """Promote a lone short first paragraph to heading when lists follow."""
    if title is not None or len(blocks) < 2:
        return blocks
    first = blocks[0]
    if not isinstance(first, ParagraphBlock) or len(first.text) > 160:
        return blocks
    if not any(isinstance(block, ListBlock) for block in blocks[1:]):
        return blocks
    return [HeadingBlock(type="heading", level=2, text=first.text), *blocks[1:]]


def _parse_ordered_line(line: str) -> ListItem | None:
    md = _ORDERED_EMPHASIS_MD.match(line)
    if md is not None:
        return _list_item_from_groups(md.group(1), md.group(2))
    plain_em = _ORDERED_EMPHASIS_PLAIN.match(line)
    if plain_em is not None:
        return _list_item_from_groups(plain_em.group(1), plain_em.group(2))
    plain = _ORDERED_PLAIN.match(line)
    if plain is not None:
        return ListItem(text=_strip_markdown_bold(plain.group(1)))
    return None


def _parse_bullet_line(line: str) -> ListItem | None:
    md = _BULLET_EMPHASIS_MD.match(line)
    if md is not None:
        return _list_item_from_groups(md.group(1), md.group(2))
    plain = _BULLET_PLAIN.match(line)
    if plain is not None:
        return ListItem(text=_strip_markdown_bold(plain.group(1)))
    return None


def _indent_width(raw: str) -> int:
    prefix = raw[: len(raw) - len(raw.lstrip(" \t"))]
    return len(prefix.expandtabs(4))


def _flatten_nested_bullet(item: ListItem, indent: int) -> ListItem:
    """Flatten an indented sub-bullet into the parent list (no nested list contract).

    ``ListBlock`` has no nesting level, so a nested item used to lose its hierarchy
    silently and read as a sibling. A visible marker keeps the sub-point readable
    without inventing a second list shape (055).
    """
    if indent < 2 or item.text.startswith("· "):
        return item
    return item.model_copy(update={"text": f"· {item.text}"})


def _list_item_from_groups(emphasis_raw: str | None, body_raw: str | None) -> ListItem | None:
    emphasis = (emphasis_raw or "").strip().rstrip(":")[:200]
    body = _strip_markdown_bold(body_raw or "").strip()
    if emphasis and body:
        return ListItem(text=body, emphasis=emphasis)
    if emphasis:
        return ListItem(text=emphasis)
    if body:
        return ListItem(text=body)
    return None


def _strip_markdown_bold(text: str) -> str:
    return _MARKDOWN_BOLD.sub(r"\1", text).strip()


def _paragraph_chunks(text: str, *, max_chars: int) -> list[ContentBlock]:
    return [ParagraphBlock(type="paragraph", text=chunk) for chunk in _chunk_text(text, max_chars=max_chars)]


def _chunk_text(text: str, *, max_chars: int) -> list[str]:
    """Split into ParagraphBlock-sized chunks (domain max_length=8000)."""
    if max_chars < 1:
        return [text[:1] or " "]
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            split_at = text.rfind("\n", start, end)
            if split_at <= start:
                split_at = text.rfind(" ", start, end)
            if split_at > start:
                end = split_at
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        start = end if end > start else start + max_chars
    return chunks or [text[:max_chars]]
