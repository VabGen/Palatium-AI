# src/palatium_ai/domain/hitl/ports.py

"""Порты хранения HITL-карточек."""

from __future__ import annotations

from typing import Protocol

from palatium_ai.domain.hitl.cards import HITLCardView


class HitlCardStore(Protocol):
    """Абстракция persistence для HITL (memory / Redis / DB)."""

    async def save(self, card: HITLCardView, *, idempotency_key: str | None = None) -> None:
        """Создаёт или обновляет карточку (non-CAS; prefer compare_and_set for transitions)."""

    async def compare_and_set(
        self,
        card: HITLCardView,
        *,
        expected_status: str,
        idempotency_key: str | None = None,
    ) -> bool:
        """Atomically write card only when stored status matches expected_status."""

    async def resolve_pending(
        self,
        card: HITLCardView,
        *,
        expected_status: str = "pending",
        idempotency_key: str,
    ) -> bool:
        """Atomically transition pending → resolved. Return False on race/conflict."""

    async def get(self, card_id: str) -> HITLCardView | None:
        """Возвращает карточку или None."""

    async def get_idempotency_key(self, card_id: str) -> str | None:
        """Ключ успешного ответа (для идемпотентного replay)."""

    async def list_cards(self) -> list[HITLCardView]:
        """Все известные карточки (для TTL sweep)."""
