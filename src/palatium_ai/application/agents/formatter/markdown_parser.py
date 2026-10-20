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
    DividerBlock,
    DocumentInteraction,
    DocumentMeta,
    FormulaBlock,
    HeadingBlock,
    IconToken,
    KeyValueBlock,
    KeyValueItem,
    ListBlock,
    ListItem,
    ParagraphBlock,
    StepItem,
    StepsBlock,
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
_CALLOUT_START = re.compile(
    r"^>\s*\[!(NOTE|WARNING|DANGER|SUCCESS|INFO)\]\s*(?P<title>.*)$",
    re.IGNORECASE,
)
_CALLOUT_BODY = re.compile(r"^>\s?(.*)$")
_TABLE_SEP = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
# Split table cells on unescaped pipes only — GFM allows a literal ``\|`` inside a cell.
_SPLIT_ROW_CELL = re.compile(r"(?<!\\)\|")
_FENCE = re.compile(r"^\s*```")
_LEADING_ICON = re.compile(
    r'^\s*<icon\s+(?:name|x)="([a-z_]+)"\s*/>\s*',
    re.IGNORECASE,
)
# Rich structured blocks (UI renders these; see rule 055 — no per-phrase hardcode).
_FORMULA_BLOCK = re.compile(r"^\s*\$\$(.+?)\$\$\s*$")
_DIVIDER = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
# Label separator may sit inside the bold (`**Label:** value`) or after it (`**Label**: value`).
_LABEL_SEP_CHARS = ":—–-"
_KV_LINE = re.compile(r"^\s*[-*]\s+\*\*(?P<label>.+?)\*\*\s*(?P<sep>[:—–-])?\s*(?P<value>.+)$")
# Panel without a bullet: `**Label:** value`. Recognised only as 2+ consecutive
# lines — a lone bold-led paragraph stays prose (055).
_KV_BARE_LINE = re.compile(r"^\s*\*\*(?P<label>.+?)\*\*\s*(?P<sep>[:—–-])?\s*(?P<value>.+)$")
_STEPS_ITEM = re.compile(r"^\s*\d+[.)]\s+\*\*(?P<title>.+?)\*\*\s*(?P<sep>[:—–-])?\s*(?P<body>.+)$")

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
        return _empty_document(task_input)

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
        if cleaned:
            blocks = (ParagraphBlock(type="paragraph", text=cleaned),)
        elif not actions and interaction == "none":
            # Nothing to render and nothing to ask → honest empty document; the layer
            # above turns it into failure_or_fallback. Never fake a whitespace block.
            return _empty_document(task_input)
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
    """Legacy JSON path — only when the whole response is valid JSON with schema_version=1."""
    stripped = raw.strip()
    if not stripped.startswith("{"):
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return None
    try:
        return parse_formatter_document(stripped)
    except ValueError, TypeError, ValidationError:
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

        block, consumed = _try_structured_block(lines, i)
        if consumed:
            flush_buf()
            if block is not None:
                blocks.append(block)
            i += consumed
            continue

        buf.append(line)
        i += 1

    flush_buf()
    return title, tuple(blocks)


def _try_structured_block(lines: list[str], index: int) -> tuple[ContentBlock | None, int]:
    """Detect a rich block (callout/divider/formula/kv/steps/table) at ``index``.

    Rich blocks are ordered by specificity, and every check that could also read a
    prose line is tested here so ``_parse_gfm_blocks`` stays a flat dispatch loop.
    Returns ``(block, lines_consumed)``; ``consumed == 0`` means "not a rich block".
    A result may carry ``block is None`` with ``consumed > 0`` only for an empty
    formula — the line is still swallowed so the literal ``$$ $$`` never leaks into prose.
    """
    line = lines[index]

    callout = _CALLOUT_START.match(line.strip())
    if callout:
        return _consume_callout(lines, index, callout.group(1), callout.group("title"))

    # Divider must be checked before a table separator: a lone `---` is a divider.
    if _DIVIDER.match(line):
        return DividerBlock(type="divider"), 1

    # Formula block: `$$E = mc^2$$` on its own line (LaTeX, not a code fence).
    formula_match = _FORMULA_BLOCK.match(line)
    if formula_match:
        latex = formula_match.group(1).strip()[:4000]
        return (FormulaBlock(type="formula", latex=latex) if latex else None), 1

    # Key-value panel: 2+ consecutive `- **Label:** value` bullets.
    kv_block, kv_consumed = _try_parse_kv_panel(lines, index)
    if kv_block is not None:
        return kv_block, kv_consumed

    # Steps / timeline: 2+ consecutive `N. **Title:** body` items.
    steps_block, steps_consumed = _try_parse_steps(lines, index)
    if steps_block is not None:
        return steps_block, steps_consumed

    # GFM pipe table — checked last so a divider line is never read as a separator.
    if _looks_like_table_header(lines, index):
        table, table_consumed = _parse_table(lines, index)
        if table is not None:
            return table, table_consumed

    return None, 0


def _split_label_separator(text: str) -> tuple[str, bool]:
    """Return ``(label, had_separator)`` — the separator may be inside the bold or after it."""
    stripped = text.strip()
    if stripped and stripped[-1] in _LABEL_SEP_CHARS:
        return stripped.rstrip(_LABEL_SEP_CHARS).strip(), True
    return stripped, False


def _try_parse_kv_panel(lines: list[str], index: int) -> tuple[KeyValueBlock | None, int]:
    """Detect 2+ consecutive ``- **Label:** value`` (or bare ``**Label:** value``) lines.

    A single match stays a normal bullet / paragraph — the panel needs two pairs to
    signal "these are parallel parameters, not prose" (055).
    """
    for pattern in (_KV_LINE, _KV_BARE_LINE):
        items, consumed = _collect_kv_items(lines, index, pattern)
        if len(items) >= 2:
            return KeyValueBlock(type="kv", items=tuple(items)), consumed
    return None, 0


def _collect_kv_items(
    lines: list[str],
    index: int,
    pattern: re.Pattern[str],
) -> tuple[list[KeyValueItem], int]:
    items: list[KeyValueItem] = []
    i = index
    while i < len(lines):
        match = pattern.match(lines[i])
        if match is None:
            break
        label, had_inline_sep = _split_label_separator(match.group("label"))
        if not had_inline_sep and match.group("sep") is None:
            break
        value = match.group("value").strip()
        if label and value:
            items.append(KeyValueItem(label=label[:200], value=value[:2000]))
        i += 1
    return items, i - index


def _try_parse_steps(lines: list[str], index: int) -> tuple[StepsBlock | None, int]:
    """Detect 2+ consecutive ``N. **Title:** body`` items as one process timeline."""
    items: list[StepItem] = []
    i = index
    while i < len(lines):
        match = _STEPS_ITEM.match(lines[i])
        if match is None:
            break
        title, had_inline_sep = _split_label_separator(match.group("title"))
        if not had_inline_sep and match.group("sep") is None:
            break
        body = match.group("body").strip()
        if title and body:
            items.append(StepItem(title=title[:200], body=body[:2000], status="pending"))
        i += 1
    if len(items) >= 2:
        return StepsBlock(type="steps", items=tuple(items)), i - index
    return None, 0


def _consume_callout(
    lines: list[str],
    index: int,
    kind: str,
    title: str,
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
        title=_clean_text_field(title.strip()) if title.strip() else None,
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
            list_items = tuple(_enrich_list_item(item) for item in block.items)
            return block.model_copy(update={"items": list_items})
        case TableBlock():
            columns = tuple(_clean_text_field(c) or " " for c in block.columns)
            rows = tuple(tuple(_clean_text_field(cell) or " " for cell in row) for row in block.rows)
            return block.model_copy(update={"columns": columns, "rows": rows})
        case KeyValueBlock():
            kv_items = tuple(
                item.model_copy(
                    update={
                        "label": _clean_text_field(item.label) or item.label,
                        "value": _clean_text_field(item.value) or item.value,
                    }
                )
                for item in block.items
            )
            return block.model_copy(update={"items": kv_items})
        case StepsBlock():
            step_items = tuple(
                item.model_copy(
                    update={
                        "title": _clean_text_field(item.title) or item.title,
                        "body": _clean_text_field(item.body) or item.body,
                    }
                )
                for item in block.items
            )
            return block.model_copy(update={"items": step_items})
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
    stripped = line.strip().removeprefix("|")
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    return [cell.replace("\\|", "|").strip() for cell in _SPLIT_ROW_CELL.split(stripped)]


def _empty_document(task_input: FormatterInput) -> ContentDocument:
    locale = ReplyLocalePolicy.normalize(task_input.response_locale) or "und"
    return ContentDocument(
        schema_version=1,
        locale=locale,
        title=None,
        blocks=(),
        actions=(),
        meta=DocumentMeta(
            confidence=0.0,
            requires_review=True,
            source_refs=(),
            interaction="none",
        ),
    )
