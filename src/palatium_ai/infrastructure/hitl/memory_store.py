# src/palatium_ai/infrastructure/hitl/memory_store.py

"""In-memory HITL store (dev / single-process)."""

from __future__ import annotations

import asyncio

from palatium_ai.domain.hitl.cards import HITLCardView


class InMemoryHitlCardStore:
    """Потокобезопасное хранилище карточек в процессе API."""

    def __init__(self) -> None:
        self._cards: dict[str, HITLCardView] = {}
        self._idempotency: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def save(self, card: HITLCardView, *, idempotency_key: str | None = None) -> None:
        """Сохраняет карточку и опционально idempotency key."""
        async with self._lock:
            self._cards[card.card_id] = card
            if idempotency_key is not None:
                self._idempotency[card.card_id] = idempotency_key

    async def compare_and_set(
        self,
        card: HITLCardView,
        *,
        expected_status: str,
        idempotency_key: str | None = None,
    ) -> bool:
        """Atomically write card only when current status matches expected."""
        async with self._lock:
            current = self._cards.get(card.card_id)
            if current is None or current.status != expected_status:
                return False
            self._cards[card.card_id] = card
            if idempotency_key is not None:
                self._idempotency[card.card_id] = idempotency_key
            return True

    async def resolve_pending(
        self,
        card: HITLCardView,
        *,
        expected_status: str = "pending",
        idempotency_key: str,
    ) -> bool:
        """Atomically write resolved card only when current status matches expected."""
        return await self.compare_and_set(
            card,
            expected_status=expected_status,
            idempotency_key=idempotency_key,
        )

    async def get(self, card_id: str) -> HITLCardView | None:
        """Возвращает карточку по id."""
        async with self._lock:
            return self._cards.get(card_id)

    async def get_idempotency_key(self, card_id: str) -> str | None:
        """Возвращает сохранённый idempotency key успешного ответа."""
        async with self._lock:
            return self._idempotency.get(card_id)

    async def list_cards(self) -> list[HITLCardView]:
        """Список всех карточек (для TTL sweep)."""
        async with self._lock:
            return list(self._cards.values())
