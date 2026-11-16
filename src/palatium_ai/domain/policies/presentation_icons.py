# src/palatium_ai/domain/policies/presentation_icons.py

"""Presentation chrome for ``ContentDocument`` — TokenIcon registry only.

Icons are sparse semantic signals (Big Tech 2026: text primary, chrome secondary),
not decoration on every heading or list row. The UI registry (``TokenIcon`` /
``ICON_NAMES``) is closed — this policy never invents names outside that allow-list.

Flow inside ``enrich``:
1. Fill missing lead-heading / callout / action defaults.
2. Prune density (strip list/kv/paragraph icons; keep only signal non-lead H2).
3. Align heading before a code fence → ``document``.

Scenario-specific phrase hardcoding is forbidden (055).
"""

from __future__ import annotations

from typing import Final

from palatium_ai.domain.content.content_document import (
    ActionKind,
    ActionSpec,
    CalloutBlock,
    CalloutTone,
    CodeBlock,
    ContentBlock,
    ContentDocument,
    DocumentKind,
    HeadingBlock,
    IconToken,
    KeyValueBlock,
    KeyValueItem,
    ListBlock,
    ListItem,
    ParagraphBlock,
    StepItem,
    StepsBlock,
)

#: First/top heading chrome by semantic class of the answer (global, not per-prompt).
_KIND_HEADING_ICON: Final[dict[DocumentKind, IconToken]] = {
    "analysis": "search",
    "recommendation": "check",
    "response": "mail",
    "letter": "mail",
    "memo": "document",
    "guide": "document",
    "report": "chart",
    "faq": "info",
}

_CALLOUT_ICON: Final[dict[CalloutTone, IconToken]] = {
    "info": "info",
    "success": "success",
    "warning": "warning",
    "danger": "danger",
}

_ACTION_ICON: Final[dict[ActionKind, IconToken]] = {
    "approve": "check",
    "reject": "x",
    "confirm": "check",
    "dismiss": "x",
    "format": "edit",
}

#: Kinds where empty heading icons stay empty (formal correspondence — no chrome).
_KIND_WITHOUT_HEADING_ICON: Final[frozenset[DocumentKind]] = frozenset({"letter", "memo", "response", "faq"})

#: Non-lead headings may keep only these — risk / outcome / notice. Decorative
#: tokens (``list``, ``document``, ``search``, ``folder``, …) flatten into noise.
_HEADING_SIGNAL_ICONS: Final[frozenset[IconToken]] = frozenset({"warning", "danger", "check", "success", "info"})


class PresentationIconPolicy:
    """Deterministic icon fill + density prune for ``ContentDocument`` — pure, no I/O."""

    @classmethod
    def enrich(cls, document: ContentDocument) -> ContentDocument:
        """Fill defaults, then prune oversaturated chrome (055 / Big Tech laconic)."""
        kind = document.meta.kind
        heading_icon = None if kind in _KIND_WITHOUT_HEADING_ICON else _KIND_HEADING_ICON.get(kind)
        new_blocks, blocks_changed = cls._enrich_blocks(document.blocks, heading_icon)
        new_actions, actions_changed = cls._enrich_actions(document.actions)
        pruned = cls._prune_density(tuple(new_blocks))
        if pruned is not None:
            new_blocks = list(pruned)
            blocks_changed = True
        code_aligned = cls._align_code_section_icons(tuple(new_blocks))
        if code_aligned is not None:
            new_blocks = list(code_aligned)
            blocks_changed = True
        if not blocks_changed and not actions_changed:
            return document
        updates: dict[str, object] = {}
        if blocks_changed:
            updates["blocks"] = tuple(new_blocks)
        if actions_changed:
            updates["actions"] = tuple(new_actions)
        return document.model_copy(update=updates)

    @classmethod
    def prune_block_row_chrome(cls, block: ContentBlock) -> ContentBlock:
        """Strip list/kv/step/paragraph icons — same density rule as ``enrich``.

        Used by ``prepare_block_for_stream_paint`` so ``block_delta`` already matches
        the final document (040: ``layout_shift_count == 0``). Lead-heading fill and
        non-lead heading prune need document position + ``meta.kind`` — those stay in
        ``enrich`` and are synced by re-emitting the aligned document.
        """
        # ``is_lead_heading=True`` preserves heading icons (unknown position mid-stream).
        return cls._prune_block(block, is_lead_heading=True)

    @classmethod
    def _enrich_blocks(
        cls,
        blocks: tuple[ContentBlock, ...],
        heading_icon: IconToken | None,
    ) -> tuple[list[ContentBlock], bool]:
        changed = False
        out: list[ContentBlock] = []
        lead_heading_filled = False
        for block in blocks:
            enrich_heading = heading_icon if not lead_heading_filled else None
            enriched = cls._enrich_block(block, heading_icon=enrich_heading)
            if (
                isinstance(block, HeadingBlock)
                and isinstance(enriched, HeadingBlock)
                and block.icon is None
                and enriched.icon is not None
            ) or isinstance(block, HeadingBlock):
                lead_heading_filled = True
            if enriched is not block:
                changed = True
            out.append(enriched)
        return out, changed

    @classmethod
    def _enrich_actions(cls, actions: tuple[ActionSpec, ...]) -> tuple[list[ActionSpec], bool]:
        changed = False
        out: list[ActionSpec] = []
        for action in actions:
            if action.icon is not None:
                out.append(action)
                continue
            icon = _ACTION_ICON.get(action.kind)
            if icon is None:
                out.append(action)
                continue
            changed = True
            out.append(action.model_copy(update={"icon": icon}))
        return out, changed

    @classmethod
    def _prune_density(cls, blocks: tuple[ContentBlock, ...]) -> tuple[ContentBlock, ...] | None:
        """Strip row chrome; keep lead heading + signal non-lead headings only."""
        changed = False
        out: list[ContentBlock] = []
        lead_seen = False
        for block in blocks:
            pruned = cls._prune_block(block, is_lead_heading=not lead_seen)
            if isinstance(block, HeadingBlock):
                lead_seen = True
            if pruned is not block:
                changed = True
            out.append(pruned)
        return tuple(out) if changed else None

    @classmethod
    def _prune_block(cls, block: ContentBlock, *, is_lead_heading: bool) -> ContentBlock:
        match block:
            case HeadingBlock() if not is_lead_heading and block.icon is not None and block.icon not in _HEADING_SIGNAL_ICONS:
                return block.model_copy(update={"icon": None})
            case ParagraphBlock() if block.icon is not None:
                return block.model_copy(update={"icon": None})
            case ListBlock():
                items = tuple(cls._prune_list_item(item) for item in block.items)
                if items == block.items:
                    return block
                return block.model_copy(update={"items": items})
            case KeyValueBlock():
                items = tuple(cls._prune_kv_item(item) for item in block.items)
                if items == block.items:
                    return block
                return block.model_copy(update={"items": items})
            case StepsBlock():
                items = tuple(cls._prune_step_item(item) for item in block.items)
                if items == block.items:
                    return block
                return block.model_copy(update={"items": items})
            case _:
                return block

    @classmethod
    def _prune_list_item(cls, item: ListItem) -> ListItem:
        return item if item.icon is None else item.model_copy(update={"icon": None})

    @classmethod
    def _prune_kv_item(cls, item: KeyValueItem) -> KeyValueItem:
        return item if item.icon is None else item.model_copy(update={"icon": None})

    @classmethod
    def _prune_step_item(cls, item: StepItem) -> StepItem:
        # Status markers are UI chrome from ``status``; a free icon doubles the glyph.
        if item.icon is None:
            return item
        return item.model_copy(update={"icon": None})

    @classmethod
    def _align_code_section_icons(cls, blocks: tuple[ContentBlock, ...]) -> tuple[ContentBlock, ...] | None:
        """Heading immediately before a code fence → ``document``, never ``chart``.

        Structural: the next block type decides chrome, not heading phrasing (055).
        """
        changed = False
        out: list[ContentBlock] = []
        for index, block in enumerate(blocks):
            nxt = blocks[index + 1] if index + 1 < len(blocks) else None
            if isinstance(block, HeadingBlock) and isinstance(nxt, CodeBlock) and block.icon in (None, "chart", "search"):
                out.append(block.model_copy(update={"icon": "document"}))
                changed = True
            else:
                out.append(block)
        return tuple(out) if changed else None

    @classmethod
    def _enrich_block(
        cls,
        block: ContentBlock,
        *,
        heading_icon: IconToken | None,
    ) -> ContentBlock:
        match block:
            case HeadingBlock() if block.icon is None and heading_icon is not None:
                return block.model_copy(update={"icon": heading_icon})
            case CalloutBlock() if block.icon is None:
                return block.model_copy(update={"icon": _CALLOUT_ICON[block.tone]})
            case _:
                return block


__all__ = ["PresentationIconPolicy"]
