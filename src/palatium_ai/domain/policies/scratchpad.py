# src/palatium_ai/domain/policies/scratchpad.py

"""Session scratchpad policy — structural slot upsert from dialog (055, no phrase lists)."""

from __future__ import annotations

import hashlib
import re

from typing import TYPE_CHECKING

from palatium_ai.domain.memory.scratchpad import ScratchpadSlot, SessionScratchpad
from palatium_ai.domain.policies.continuity import ContinuityPolicy

if TYPE_CHECKING:
    from palatium_ai.domain.memory.turns import DialogTurnWindow

_MAX_SLOTS = 8
_KEY_MAX = 80


class SessionScratchpadPolicy:
    """Pure policy: merge short user intents into a capped thread scratchpad."""

    max_slots: int = _MAX_SLOTS

    @classmethod
    def merge_from_dialog(
        cls,
        current: SessionScratchpad,
        dialog: DialogTurnWindow | None,
    ) -> SessionScratchpad:
        """Upsert recent short user intents; newest win; drop oldest beyond cap."""
        intents = ContinuityPolicy.recent_short_user_intents(dialog, max_items=cls.max_slots)
        if not intents:
            return current

        by_key: dict[str, ScratchpadSlot] = {slot.key: slot for slot in current.slots}
        order: list[str] = [slot.key for slot in current.slots]

        for text in intents:
            key = cls.slot_key(text)
            slot = ScratchpadSlot(key=key, text=text, kind="fact", confidence=1.0)
            if key in by_key:
                by_key[key] = slot
                order = [k for k in order if k != key]
                order.append(key)
            else:
                by_key[key] = slot
                order.append(key)

        if len(order) > cls.max_slots:
            order = order[-cls.max_slots :]
        slots = tuple(by_key[k] for k in order if k in by_key)
        return SessionScratchpad(thread_id=current.thread_id, slots=slots)

    @staticmethod
    def slot_key(text: str) -> str:
        """Stable key from normalized text (no language-specific lists)."""
        normalized = re.sub(r"\s+", " ", text.strip().lower())
        slug = re.sub(r"[^a-z0-9а-яё_-]+", "-", normalized, flags=re.IGNORECASE).strip("-")[:_KEY_MAX]
        if slug:
            return f"u:{slug}"
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        return f"u:{digest}"
