# src/palatium_ai/application/agents/formatter/stream_paint.py

"""Prepare a closed block before ``block_delta`` so preview matches final render.

``align_formatter_meta`` still runs ``promote_label_lists_to_kv`` / nesting normalize
/ ``PresentationIconPolicy`` on the finished document. If the stream painted the
raw LLM list (or row ``search`` icons) and the final path promoted to ``kv`` or
pruned density chrome, the client snaps — the layout shift Hybrid SSE forbids
(``layout_shift_count == 0``, evolution-to-big-tech / 040).

Apply the same per-block transforms at paint time. Document-level steps↔list
chrome that needs ``response_shape`` stays in align and is skipped once blocks
are already on screen (see ``parsing.align_formatter_meta``).
"""

from __future__ import annotations

from palatium_ai.domain.content.content_document import (
    ContentBlock,
    ListBlock,
    ListItem,
    normalize_list_item_nesting,
)
from palatium_ai.domain.policies.mechanical_restructure import MechanicalRestructurePolicy
from palatium_ai.domain.policies.presentation_icons import PresentationIconPolicy


def prepare_block_for_stream_paint(block: ContentBlock) -> ContentBlock:
    """Return the block the client should paint — same contract as the final document."""
    normalized = _normalize_list_block(block)
    promoted = MechanicalRestructurePolicy.promote_label_lists_to_kv((normalized,))
    shaped = promoted[0] if promoted is not None else normalized
    return PresentationIconPolicy.prune_block_row_chrome(shaped)


def _normalize_list_block(block: ContentBlock) -> ContentBlock:
    if not isinstance(block, ListBlock):
        return block
    items: list[ListItem] = []
    changed = False
    for item in block.items:
        text, level = normalize_list_item_nesting(item.text, item.level)
        if text != item.text or level != item.level:
            changed = True
            items.append(item.model_copy(update={"text": text, "level": level}))
        else:
            items.append(item)
    if not changed:
        return block
    return block.model_copy(update={"items": tuple(items)})
