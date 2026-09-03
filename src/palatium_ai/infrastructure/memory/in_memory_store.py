# src/palatium_ai/infrastructure/memory/in_memory_store.py

"""Process-local MemoryPort (dev / tests)."""

from __future__ import annotations

import asyncio
import re

from palatium_ai.core.types.coerce import coerce_float
from palatium_ai.domain.memory.pii import mask_memory_value, memory_contains_pii


class InMemoryMemoryPort:
    """Cross-thread memory keyed by namespace tuple + key."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._items: dict[tuple[tuple[str, ...], str], dict[str, object]] = {}

    async def put(self, *, namespace: tuple[str, ...], key: str, value: dict[str, object]) -> None:
        """Upsert a memory item under namespace/key."""
        async with self._lock:
            self._items[(namespace, key)] = dict(value)

    async def get(self, *, namespace: tuple[str, ...], key: str) -> dict[str, object] | None:
        """Fetch one item or None."""
        async with self._lock:
            item = self._items.get((namespace, key))
            if item is None:
                return None
            return mask_memory_value(dict(item), contains_pii=memory_contains_pii(item))

    async def search(
        self,
        *,
        namespace: tuple[str, ...],
        query: str,
        limit: int = 8,
    ) -> list[dict[str, object]]:
        """Token overlap × confidence within a namespace (budgeted)."""
        tokens = {t for t in re.findall(r"[a-zA-Zа-яА-Я0-9_]{2,}", query.lower())}
        async with self._lock:
            scored: list[tuple[float, dict[str, object]]] = []
            for (ns, _key), value in self._items.items():
                if ns != namespace:
                    continue
                blob = " ".join(str(v) for v in value.values()).lower()
                overlap = float(sum(1 for token in tokens if token in blob)) if tokens else 1.0
                confidence = max(0.0, min(1.0, coerce_float(value.get("confidence", 0.0))))
                score = overlap * (0.5 + 0.5 * confidence)
                if score > 0 or not tokens:
                    enriched = mask_memory_value(dict(value), contains_pii=memory_contains_pii(value))
                    enriched["_score"] = round(score, 4)
                    scored.append((score, enriched))
            scored.sort(key=lambda item: item[0], reverse=True)
            return [item for _, item in scored[: max(1, limit)]]

    async def forget(self, *, namespace: tuple[str, ...], key: str) -> bool:
        """Remove one item from namespace/key."""
        async with self._lock:
            return self._items.pop((namespace, key), None) is not None
