# src/palatium_ai/application/agents/formatter/markdown_parser.py

"""Parse Formatter GFM (+ HITL XML tags) into ContentDocument after the stream ends.

Regex/stdlib only — no markdown-it-py unless tables/nested lists prove insufficient.
JSON ContentDocument remains a fallback for cache/regression compatibility.
"""

from __future__ import annotations

import json
import re

from uuid import uuid4

from pydantic import ValidationError

from palatium_ai.application.agents.formatter.icon_sanitizer import (
    coerce_icon_name,
    count_icon_tokens,
    normalize_icon_markup,
    strip_emoji,
    strip_icon_tokens,
)
from palatium_ai.application.agents.formatter.parsing import parse_formatter_document
from palatium_ai.core.logging import get_logger
from palatium_ai.core.logging.context import turn_id_var
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content.content_document import (
    ActionKind,
    ActionSpec,
    CalloutBlock,
    CalloutTone,
    ContentBlock,
    ContentDocument,
    DocumentInteraction,
    DocumentMeta,
    HeadingBlock,
    IconToken,
    ListBlock,
    ListItem,
    ParagraphBlock,
    TableBlock,
)
from palatium_ai.domain.content.markdown_blocks import prose_to_blocks
from palatium_ai.domain.policies.locale import ReplyLocalePolicy

_HITL_ACTION = re.compile(
    r"<hitl-action\b([^>]*)/?>",
    re.IGNORECASE,
)
_HITL_CHOICE = re.compile(
    r"<hitl-choice\b([^>]*)/?>",
    re.IGNORECASE,
)
_ATTR = re.compile(r"""(\w+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_CITE = re.compile(r"\[(\d+)\]")
_CALLOUT_START = re.compile(r"^>\s*\[!(NOTE|WARNING|DANGER|SUCCESS|INFO)\]\s*$", re.IGNORECASE)
_CALLOUT_BODY = re.compile(r"^>\s?(.*)$")
_TABLE_SEP = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_FENCE = re.compile(r"^\s*```")
_LEADING_ICON = re.compile(
    r'^\s*<icon\s+(?:name|x)="([a-z_]+)"\s*/>\s*',
    re.IGNORECASE,
)

logger = get_logger(__name__)

_CALLOUT_TONE: dict[str, CalloutTone] = {
    "NOTE": "info",
    "INFO": "info",
    "SUCCESS": "success",
    "WARNING": "warning",
    "DANGER": "danger",
}
_CALLOUT_ICON: dict[CalloutTone, IconToken] = {
    "info": "info",
    "success": "success",
    "warning": "warning",
    "danger": "danger",
}
_ACTION_KIND_MAP: dict[str, ActionKind] = {
    "approve": "approve",
    "reject": "reject",
    "confirm": "confirm",
    "dismiss": "dismiss",
    "custom": "custom",
    "format": "format",
}


def markdown_to_content_document(markdown: str, task_input: FormatterInput) -> ContentDocument:
    """Build a ContentDocument from final Formatter markdown (or legacy JSON)."""
    raw = (markdown or "").strip()
    if not raw:
        return _empty_paragraph_doc(task_input)

    json_doc = _try_json_document(raw)
    if json_doc is not None:
        # Legacy JSON path: still strip emoji / orphan icon tokens from text fields.
        return json_doc.model_copy(
            update={
                "title": _clean_text_field(json_doc.title),
                "blocks": _normalize_blocks(_apply_icons_and_strip_emoji(json_doc.blocks)),
            }
        )

    cleaned, actions, interaction = _extract_hitl(raw)
    cite_nums = {int(m.group(1)) for m in _CITE.finditer(cleaned)}
    title, blocks = _parse_gfm_blocks(cleaned)
    if not blocks:
        blocks = (ParagraphBlock(type="paragraph", text=cleaned or " "),)
    title = _clean_text_field(title) if title else None
    blocks = _normalize_blocks(_apply_icons_and_strip_emoji(blocks))

    locale = ReplyLocalePolicy.normalize(task_input.response_locale) or "und"
    source_refs = _source_refs_from_cites(cite_nums, task_input)
    return ContentDocument(
        schema_version=1,
        locale=locale,
        title=title,
        blocks=blocks,
        actions=tuple(actions),
        meta=DocumentMeta(
            confidence=0.85,
            requires_review=task_input.requires_review,
            source_refs=source_refs,
            interaction=interaction,
        ),
    )


def _try_json_document(raw: str) -> ContentDocument | None:
    stripped = raw.strip()
    if not (stripped.startswith("{") and '"schema_version"' in stripped):
        return None
    try:
        return parse_formatter_document(stripped)
    except (ValueError, TypeError, json.JSONDecodeError, ValidationError):  # fmt: skip
        return None


def _extract_hitl(
    text: str,
) -> tuple[str, list[ActionSpec], DocumentInteraction]:
    actions: list[ActionSpec] = []
    interaction: DocumentInteraction = "none"

    def _action_repl(match: re.Match[str]) -> str:
        nonlocal interaction
        attrs = _parse_attrs(match.group(1))
        kind_raw = (attrs.get("kind") or "custom").strip().lower()
        action_kind = _ACTION_KIND_MAP.get(kind_raw, "custom")
        if kind_raw == "choice":
            action_kind = "custom"
            interaction = "choice"
        label = (attrs.get("label") or action_kind).strip() or action_kind
        if action_kind in {"confirm", "approve"}:
            interaction = "confirm" if interaction == "none" else interaction
        elif action_kind == "format":
            interaction = "choice"
        actions.append(
            ActionSpec(
                action_id=f"md-{uuid4().hex[:12]}",
                label=label[:200],
                kind=action_kind,
                style="primary" if action_kind in {"confirm", "approve"} else "secondary",
                requires_confirmation=action_kind in {"confirm", "approve"},
            )
        )
        return ""

    def _choice_repl(match: re.Match[str]) -> str:
        nonlocal interaction
        attrs = _parse_attrs(match.group(1))
        options = _parse_options_attr(attrs.get("options") or "[]")
        if options:
            interaction = "choice"
        actions.extend(
            ActionSpec(
                action_id=f"md-{uuid4().hex[:12]}",
                label=opt[:200],
                kind="custom",
                style="secondary",
            )
            for opt in options
        )
        return ""

    cleaned = _HITL_ACTION.sub(_action_repl, text)
    cleaned = _HITL_CHOICE.sub(_choice_repl, cleaned)
    return cleaned.strip(), actions, interaction


def _parse_attrs(raw: str) -> dict[str, str]:
    return {m.group(1).lower(): (m.group(2) if m.group(2) is not None else m.group(3) or "") for m in _ATTR.finditer(raw)}


def _parse_options_attr(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()][:12]


def _source_refs_from_cites(nums: set[int], task_input: FormatterInput) -> tuple[str, ...]:
    from palatium_ai.domain.attachments.citations import citation_refs_from_untrusted_context

    refs = citation_refs_from_untrusted_context(task_input.context_packet.untrusted_context)
    if not refs or not nums:
        return ()
    # Map [1] → first attachment basename, etc. (1-based).
    ordered = list(refs)
    picked = [ordered[n - 1] for n in sorted(nums) if 1 <= n <= len(ordered)]
    return tuple(dict.fromkeys(picked))


def _parse_gfm_blocks(text: str) -> tuple[str | None, tuple[ContentBlock, ...]]:
    lines = text.splitlines()
    blocks: list[ContentBlock] = []
    title: str | None = None
    buf: list[str] = []
    i = 0
    in_fence = False

    def flush_buf() -> None:
        nonlocal title
        chunk = "\n".join(buf).strip()
        buf.clear()
        if not chunk:
            return
        t, parsed = prose_to_blocks(chunk)
        if title is None and t is not None:
            title = t
        blocks.extend(parsed)

    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line) or in_fence:
            if _FENCE.match(line):
                in_fence = not in_fence
            buf.append(line)
            i += 1
            continue

        callout = _CALLOUT_START.match(line.strip())
        if callout:
            flush_buf()
            block, consumed = _consume_callout(lines, i, callout.group(1))
            blocks.append(block)
            i += consumed
            continue

        if _looks_like_table_header(lines, i):
            flush_buf()
            table, consumed = _parse_table(lines, i)
            if table is not None:
                blocks.append(table)
                i += consumed
                continue

        buf.append(line)
        i += 1

    flush_buf()
    return title, tuple(blocks)


def _consume_callout(
    lines: list[str],
    index: int,
    kind: str,
) -> tuple[CalloutBlock, int]:
    tone = _CALLOUT_TONE[kind.upper()]
    body_lines: list[str] = []
    i = index + 1
    while i < len(lines):
        body_m = _CALLOUT_BODY.match(lines[i])
        if not body_m:
            break
        body_lines.append(body_m.group(1))
        i += 1
    body = "\n".join(body_lines).strip() or " "
    leading_icon, body = _pop_leading_icon(body)
    block = CalloutBlock(
        type="callout",
        tone=tone,
        title=None,
        body=body[:4000],
        icon=leading_icon or _CALLOUT_ICON[tone],
    )
    return block, i - index


def _apply_icons_and_strip_emoji(blocks: tuple[ContentBlock, ...]) -> tuple[ContentBlock, ...]:
    return tuple(_enrich_block(block) for block in blocks)


def _normalize_blocks(blocks: tuple[ContentBlock, ...]) -> tuple[ContentBlock, ...]:
    """Merge orphan icon-only blocks into the next block; join adjacent ordered lists."""
    if not blocks:
        return blocks
    merged_icons = _merge_orphan_icons(blocks)
    return _merge_adjacent_ordered_lists(merged_icons)


def _is_icon_only_block(block: ContentBlock) -> bool:
    match block:
        case ParagraphBlock(icon=icon, text=text) | HeadingBlock(icon=icon, text=text):
            return icon is not None and not text.strip()
        case _:
            return False


def _attach_icon(block: ContentBlock, icon: IconToken) -> ContentBlock:
    match block:
        case HeadingBlock() | ParagraphBlock() | CalloutBlock():
            if block.icon is not None:
                return block
            return block.model_copy(update={"icon": icon})
        case ListBlock() if block.items:
            first = block.items[0]
            if first.icon is not None:
                return block
            items = (first.model_copy(update={"icon": icon}), *block.items[1:])
            return block.model_copy(update={"items": items})
        case _:
            return block


def _merge_orphan_icons(blocks: tuple[ContentBlock, ...]) -> tuple[ContentBlock, ...]:
    out: list[ContentBlock] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if _is_icon_only_block(block) and i + 1 < len(blocks):
            icon = getattr(block, "icon", None)
            nxt = blocks[i + 1]
            if icon is not None and not _is_icon_only_block(nxt):
                out.append(_attach_icon(nxt, icon))
                i += 2
                continue
        out.append(block)
        i += 1
    return tuple(out) or blocks


def _merge_adjacent_ordered_lists(blocks: tuple[ContentBlock, ...]) -> tuple[ContentBlock, ...]:
    if not blocks:
        return blocks
    out: list[ContentBlock] = []
    for block in blocks:
        if (
            isinstance(block, ListBlock)
            and block.style == "ordered"
            and out
            and isinstance(out[-1], ListBlock)
            and out[-1].style == "ordered"
        ):
            prev = out[-1]
            out[-1] = prev.model_copy(update={"items": prev.items + block.items})
            continue
        out.append(block)
    return tuple(out)


def _enrich_block(block: ContentBlock) -> ContentBlock:
    match block:
        case HeadingBlock():
            icon, text = _pop_leading_icon(block.text)
            return block.model_copy(update={"text": text, "icon": icon or block.icon})
        case ParagraphBlock():
            icon, text = _pop_leading_icon(block.text)
            return block.model_copy(update={"text": text, "icon": icon or block.icon})
        case CalloutBlock():
            icon, body = _pop_leading_icon(block.body)
            title = _clean_text_field(block.title) if block.title else None
            return block.model_copy(
                update={
                    "title": title,
                    "body": body,
                    "icon": icon or block.icon,
                }
            )
        case ListBlock():
            items = tuple(_enrich_list_item(item) for item in block.items)
            return block.model_copy(update={"items": items})
        case TableBlock():
            columns = tuple(_clean_text_field(c) or " " for c in block.columns)
            rows = tuple(tuple(_clean_text_field(cell) or " " for cell in row) for row in block.rows)
            return block.model_copy(update={"columns": columns, "rows": rows})
        case _:
            return block


def _enrich_list_item(item: ListItem) -> ListItem:
    icon, text = _pop_leading_icon(item.text)
    emphasis = _clean_text_field(item.emphasis) if item.emphasis else None
    return item.model_copy(update={"text": text, "icon": icon or item.icon, "emphasis": emphasis})


def _pop_leading_icon(text: str) -> tuple[IconToken | None, str]:
    """Pull a leading ``<icon name|x="…"/>`` into a typed icon; drop invalid / leftover tokens."""
    normalized = normalize_icon_markup(text)
    match = _LEADING_ICON.match(normalized)
    if match is None:
        return None, _clean_text_field(normalized) or " "
    icon = coerce_icon_name(match.group(1))
    rest = normalized[match.end() :]
    return icon, _clean_text_field(rest) or " "


def _clean_text_field(text: str | None) -> str | None:
    if text is None:
        return None
    normalized = normalize_icon_markup(text)
    mid_count = count_icon_tokens(normalized)
    if mid_count:
        logger.warning(
            "icon_mid_text_stripped",
            icon_count=mid_count,
            turn_id=turn_id_var.get(),
        )
    cleaned = strip_emoji(strip_icon_tokens(normalized)).strip()
    return cleaned or None


def _looks_like_table_header(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    header = lines[index].strip()
    sep = lines[index + 1].strip()
    return "|" in header and bool(_TABLE_SEP.match(sep))


def _parse_table(lines: list[str], index: int) -> tuple[TableBlock | None, int]:
    header_cells = _split_row(lines[index])
    if len(header_cells) < 1:
        return None, 1
    rows: list[tuple[str, ...]] = []
    i = index + 2
    while i < len(lines):
        raw = lines[i].strip()
        if not raw or "|" not in raw:
            break
        cells = _split_row(lines[i])
        if len(cells) != len(header_cells):
            # Pad / trim to header width for resilience.
            if len(cells) < len(header_cells):
                cells = cells + [""] * (len(header_cells) - len(cells))
            else:
                cells = cells[: len(header_cells)]
        rows.append(tuple(cells))
        i += 1
    if not rows:
        return None, 2
    return (
        TableBlock(type="table", columns=tuple(header_cells), rows=tuple(rows)),
        i - index,
    )


def _split_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def _empty_paragraph_doc(task_input: FormatterInput) -> ContentDocument:
    locale = ReplyLocalePolicy.normalize(task_input.response_locale) or "und"
    return ContentDocument(
        schema_version=1,
        locale=locale,
        title=None,
        blocks=(ParagraphBlock(type="paragraph", text=" "),),
        actions=(),
        meta=DocumentMeta(
            confidence=0.0,
            requires_review=True,
            source_refs=(),
            interaction="none",
        ),
    )
