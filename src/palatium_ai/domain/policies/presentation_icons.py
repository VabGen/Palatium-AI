# src/palatium_ai/domain/policies/presentation_icons.py

"""Fill missing ``IconToken`` slots for any answer shape — TokenIcon registry only.

Icons are presentation chrome, not content. The Formatter may omit them; the UI
registry (``TokenIcon`` / ``ICON_NAMES``) is closed, so this policy never invents
names outside that allow-list and never overrides an icon the model already set.

Applies to every scenario (analysis, plan, comparison, guide, …): one mapping from
``DocumentKind`` → heading chrome, plus tone/action defaults. Scenario-specific
hardcoding of phrases is forbidden (055).
"""

from __future__ import annotations

from typing import Final

from palatium_ai.domain.content.content_document import (
    ActionKind,
    ActionSpec,
    CalloutBlock,
    CalloutTone,
    ContentBlock,
    ContentDocument,
    DocumentKind,
    HeadingBlock,
    IconToken,
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


class PresentationIconPolicy:
    """Deterministic icon fill for ``ContentDocument`` — pure, no I/O."""

    @classmethod
    def enrich(cls, document: ContentDocument) -> ContentDocument:
        """Assign missing icons; leave explicit model choices untouched."""
        kind = document.meta.kind
        heading_icon = None if kind in _KIND_WITHOUT_HEADING_ICON else _KIND_HEADING_ICON.get(kind)
        blocks_changed = False
        first_heading_done = False
        new_blocks: list[ContentBlock] = []
        for block in document.blocks:
            enriched = cls._enrich_block(
                block,
                heading_icon=heading_icon,
                first_heading_done=first_heading_done,
            )
            if enriched is not block:
                blocks_changed = True
            if isinstance(enriched, HeadingBlock):
                first_heading_done = True
            new_blocks.append(enriched)

        actions_changed = False
        new_actions: list[ActionSpec] = []
        for action in document.actions:
            if action.icon is not None:
                new_actions.append(action)
                continue
            icon = _ACTION_ICON.get(action.kind)
            if icon is None:
                new_actions.append(action)
                continue
            actions_changed = True
            new_actions.append(action.model_copy(update={"icon": icon}))

        if not blocks_changed and not actions_changed:
            return document
        updates: dict[str, object] = {}
        if blocks_changed:
            updates["blocks"] = tuple(new_blocks)
        if actions_changed:
            updates["actions"] = tuple(new_actions)
        return document.model_copy(update=updates)

    @classmethod
    def _enrich_block(
        cls,
        block: ContentBlock,
        *,
        heading_icon: IconToken | None,
        first_heading_done: bool,
    ) -> ContentBlock:
        match block:
            case HeadingBlock() if block.icon is None and heading_icon is not None:
                # One chrome icon on the lead heading (or any H1) — not on every H2/H3.
                if block.level == 1 or not first_heading_done:
                    return block.model_copy(update={"icon": heading_icon})
                return block
            case CalloutBlock() if block.icon is None:
                return block.model_copy(update={"icon": _CALLOUT_ICON[block.tone]})
            case _:
                # Steps keep numeric markers unless status/icon was set (semanticIcons).
                # List / kv / table / chart — no invented per-row icons (noise).
                return block


__all__ = ["PresentationIconPolicy"]
