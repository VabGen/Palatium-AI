# src/palatium_ai/infrastructure/memory/in_memory_store.py

"""Process-local MemoryPort (dev / tests)."""

from __future__ import annotations

import asyncio
import re

from dataclasses import dataclass
from datetime import UTC, datetime

from palatium_ai.core.types.coerce import coerce_float
from palatium_ai.domain.memory.pii import mask_memory_value, memory_contains_pii
from palatium_ai.domain.memory.promotion import PromotionCandidate
from palatium_ai.infrastructure.memory.user_scope import resolve_user_id


@dataclass
class _AccessMeta:
    access_frequency: int = 0
    last_accessed: datetime | None = None
    promoted_at: datetime | None = None


class InMemoryMemoryPort:
    """Cross-thread memory keyed by namespace tuple + key."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._items: dict[tuple[tuple[str, ...], str], dict[str, object]] = {}
        self._meta: dict[tuple[tuple[str, ...], str], _AccessMeta] = {}

    async def put(self, *, namespace: tuple[str, ...], key: str, value: dict[str, object]) -> None:
        """Upsert a memory item under namespace/key."""
        async with self._lock:
            slot = (namespace, key)
            self._items[slot] = dict(value)
            self._meta.setdefault(slot, _AccessMeta())

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
            for (ns, entry_key), value in self._items.items():
                if ns != namespace:
                    continue
                blob = " ".join(str(v) for v in value.values()).lower()
                overlap = float(sum(1 for token in tokens if token in blob)) if tokens else 1.0
                confidence = max(0.0, min(1.0, coerce_float(value.get("confidence", 0.0))))
                score = overlap * (0.5 + 0.5 * confidence)
                if score > 0 or not tokens:
                    enriched = mask_memory_value(dict(value), contains_pii=memory_contains_pii(value))
                    enriched["_score"] = round(score, 4)
                    enriched["_entry_key"] = entry_key
                    scored.append((score, enriched))
            scored.sort(key=lambda item: item[0], reverse=True)
            return [item for _, item in scored[: max(1, limit)]]

    async def forget(self, *, namespace: tuple[str, ...], key: str) -> bool:
        """Remove one item from namespace/key."""
        async with self._lock:
            slot = (namespace, key)
            self._meta.pop(slot, None)
            return self._items.pop(slot, None) is not None

    async def bump_access(self, *, namespace: tuple[str, ...], key: str) -> int:
        """Increment access_frequency; return new count (0 if missing)."""
        async with self._lock:
            slot = (namespace, key)
            if slot not in self._items:
                return 0
            meta = self._meta.setdefault(slot, _AccessMeta())
            meta.access_frequency += 1
            meta.last_accessed = datetime.now(UTC)
            return meta.access_frequency

    async def list_promotion_candidates(
        self,
        *,
        user_id: str,
        min_access_frequency: int,
        min_importance: float,
        limit: int = 32,
    ) -> list[PromotionCandidate]:
        """Rows for one user_id not yet promoted that meet hard floors."""
        uid = user_id.strip()
        if not uid:
            return []
        safe_limit = max(1, min(limit, 128))
        async with self._lock:
            out: list[PromotionCandidate] = []
            for (namespace, entry_key), value in self._items.items():
                owner = resolve_user_id(namespace, value)
                if owner != uid:
                    continue
                meta = self._meta.get((namespace, entry_key), _AccessMeta())
                if meta.promoted_at is not None:
                    continue
                if meta.access_frequency < min_access_frequency:
                    continue
                importance = max(
                    0.0,
                    min(1.0, coerce_float(value.get("importance", value.get("confidence", 0.0)))),
                )
                if importance < min_importance:
                    continue
                text = str(value.get("text", "")).strip()
                if not text:
                    continue
                out.append(
                    PromotionCandidate(
                        namespace=namespace,
                        entry_key=entry_key,
                        text=text[:2000],
                        kind=str(value.get("kind", "fact"))[:32],
                        importance=importance,
                        access_frequency=meta.access_frequency,
                        user_id=owner,
                        confidence=max(0.0, min(1.0, coerce_float(value.get("confidence", 0.0)))),
                        contains_pii=bool(value.get("contains_pii", False)),
                        last_accessed=meta.last_accessed,
                        promoted_at=meta.promoted_at,
                    )
                )
                if len(out) >= safe_limit:
                    break
            return out

    async def mark_promoted(self, *, namespace: tuple[str, ...], key: str) -> bool:
        """Stamp promoted_at; returns True when a row was updated."""
        async with self._lock:
            slot = (namespace, key)
            if slot not in self._items:
                return False
            meta = self._meta.setdefault(slot, _AccessMeta())
            if meta.promoted_at is not None:
                return False
            meta.promoted_at = datetime.now(UTC)
            return True
