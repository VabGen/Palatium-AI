# src/palatium_ai/application/services/session_scratchpad.py

"""Load/save thread SessionScratchpad via MemoryPort (sync, hot-path safe)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING

from palatium_ai.core.logging import get_logger
from palatium_ai.domain.memory.namespaces import thread_namespace
from palatium_ai.domain.memory.scratchpad import ScratchpadSlot, SessionScratchpad
from palatium_ai.domain.memory.turns import DialogTurnWindow
from palatium_ai.domain.policies.memory_mutation import MemoryMutationPolicy
from palatium_ai.domain.policies.scratchpad import SessionScratchpadPolicy

if TYPE_CHECKING:
    from palatium_ai.domain.memory.ports import MemoryPort

logger = get_logger(__name__)

SCRATCHPAD_ENTRY_KEY = "session_scratchpad"


class SessionScratchpadService:
    """Thread scratchpad persistence; None memory_port → no-op empty pads."""

    def __init__(self, memory_port: MemoryPort | None) -> None:
        self._memory_port = memory_port

    async def load(self, *, thread_id: str) -> SessionScratchpad:
        """Load pad or empty; corrupt payloads fail soft to empty."""
        tid = thread_id.strip()
        empty = SessionScratchpad(thread_id=tid, slots=())
        if self._memory_port is None or not tid:
            return empty
        raw = await self._memory_port.get(namespace=thread_namespace(tid), key=SCRATCHPAD_ENTRY_KEY)
        if raw is None:
            return empty
        try:
            return _decode_scratchpad(tid, raw)
        except (TypeError, ValueError, KeyError) as exc:
            logger.warning(
                "session_scratchpad.load_corrupt",
                thread_id=tid,
                error=str(exc)[:200],
            )
            return empty

    async def save(self, pad: SessionScratchpad) -> None:
        """Upsert full pad blob under thread namespace."""
        if self._memory_port is None:
            return
        tid = pad.thread_id.strip()
        if not tid:
            return
        value = {
            "thread_id": tid,
            "slots_json": json.dumps(
                [slot.model_dump() for slot in pad.slots],
                ensure_ascii=False,
            ),
            "kind": "scratchpad",
            "confidence": 1.0,
            "text": "; ".join(slot.text for slot in pad.slots)[:2000] or "(empty scratchpad)",
        }
        await self._memory_port.put(
            namespace=thread_namespace(tid),
            key=SCRATCHPAD_ENTRY_KEY,
            value=value,
        )

    async def refresh_from_dialog(
        self,
        *,
        thread_id: str,
        dialog: DialogTurnWindow | None,
    ) -> SessionScratchpad:
        """Merge short user intents from dialog and persist (sync, no LLM)."""
        current = await self.load(thread_id=thread_id)
        updated = SessionScratchpadPolicy.merge_from_dialog(current, dialog)
        if updated.slots != current.slots:
            await self.save(updated)
        return updated

    async def forget_matching(self, *, thread_id: str, subject: str) -> tuple[str, ...]:
        """Drop pinned slots about ``subject`` after a forget was approved (060 fan-out).

        The scratchpad is a cheap cache of the thread's salient notes, injected into
        recall ahead of durable memory. A forgotten fact left pinned here keeps being
        answered in the same thread even though medium/L4 were cleared, so forget must
        clear every tier that can re-inject it. Returns the removed texts for audit.
        """
        target = subject.strip()
        if self._memory_port is None or not target:
            return ()
        current = await self.load(thread_id=thread_id)
        removed = tuple(slot.text for slot in current.slots if MemoryMutationPolicy.shares_subject(slot.text, target))
        if not removed:
            return ()
        kept = tuple(slot for slot in current.slots if slot.text not in removed)
        await self.save(SessionScratchpad(thread_id=current.thread_id, slots=kept))
        return removed

    async def supersede_matching(self, *, thread_id: str, text: str) -> tuple[str, ...]:
        """Drop stale pins for the subject an approved write just replaced (060 fan-out).

        Pins score above durable hits, so a pre-write pin («порт 5432») would keep
        outranking the value the human just approved («порт 5433») in this thread.
        The written text itself is kept — it is the current truth.
        """
        target = text.strip()
        if self._memory_port is None or not target:
            return ()
        current = await self.load(thread_id=thread_id)
        removed = tuple(
            slot.text
            for slot in current.slots
            if slot.text.strip() != target and MemoryMutationPolicy.shares_subject(slot.text, target)
        )
        if not removed:
            return ()
        kept = tuple(slot for slot in current.slots if slot.text not in removed)
        await self.save(SessionScratchpad(thread_id=current.thread_id, slots=kept))
        return removed


def _decode_scratchpad(thread_id: str, raw: dict[str, object]) -> SessionScratchpad:
    slots_raw = raw.get("slots_json")
    if isinstance(slots_raw, str) and slots_raw.strip():
        parsed = json.loads(slots_raw)
    elif isinstance(raw.get("slots"), list):
        parsed = raw["slots"]
    else:
        return SessionScratchpad(thread_id=thread_id, slots=())
    if not isinstance(parsed, list):
        return SessionScratchpad(thread_id=thread_id, slots=())
    slots: list[ScratchpadSlot] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        slots.append(ScratchpadSlot.model_validate(item))
    return SessionScratchpad(thread_id=thread_id, slots=tuple(slots))
