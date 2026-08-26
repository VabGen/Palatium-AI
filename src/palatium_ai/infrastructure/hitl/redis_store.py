# src/palatium_ai/infrastructure/hitl/redis_store.py

"""Redis-backed HITL card store."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from palatium_ai.domain.hitl.cards import HITLCardView

if TYPE_CHECKING:
    from redis.asyncio import Redis

_CARD_SUFFIX = "card"
_IDEM_SUFFIX = "idem"
# Держим карточку после expires_at для conflict/replay и эскалации
_RETENTION_AFTER_EXPIRY_SECONDS = 24 * 60 * 60

# Atomic status transition: overwrite only when stored status matches expected.
# ARGV: expected_status, new_json, idempotency_key (empty = skip), ttl_seconds
_COMPARE_AND_SET_LUA = """
local current = redis.call('GET', KEYS[1])
if not current then
  return 0
end
local ok, obj = pcall(cjson.decode, current)
if (not ok) or (type(obj) ~= 'table') or (obj['status'] ~= ARGV[1]) then
  return 0
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', tonumber(ARGV[4]))
if ARGV[3] ~= '' then
  redis.call('SET', KEYS[2], ARGV[3], 'EX', tonumber(ARGV[4]))
end
return 1
"""


class RedisHitlCardStore:
    """HITL persistence в Redis (multi-process safe)."""

    def __init__(self, client: Redis, *, key_prefix: str = "palatium:hitl:") -> None:
        self._client = client
        self._prefix = key_prefix

    def _card_key(self, card_id: str) -> str:
        return f"{self._prefix}{_CARD_SUFFIX}:{card_id}"

    def _idem_key(self, card_id: str) -> str:
        return f"{self._prefix}{_IDEM_SUFFIX}:{card_id}"

    def _ttl_seconds(self, card: HITLCardView) -> int:
        now = datetime.now(UTC)
        expires = card.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        remaining = int((expires - now).total_seconds()) + _RETENTION_AFTER_EXPIRY_SECONDS
        return max(60, remaining)

    async def save(self, card: HITLCardView, *, idempotency_key: str | None = None) -> None:
        """Пишет карточку (и idempotency key) в Redis с TTL."""
        ttl = self._ttl_seconds(card)
        pipe = self._client.pipeline()
        pipe.set(self._card_key(card.card_id), card.model_dump_json(), ex=ttl)
        if idempotency_key is not None:
            pipe.set(self._idem_key(card.card_id), idempotency_key, ex=ttl)
        await pipe.execute()

    async def compare_and_set(
        self,
        card: HITLCardView,
        *,
        expected_status: str,
        idempotency_key: str | None = None,
    ) -> bool:
        """Lua CAS: write card only if stored status matches expected_status."""
        ttl = self._ttl_seconds(card)
        result = await self._client.eval(
            _COMPARE_AND_SET_LUA,
            2,
            self._card_key(card.card_id),
            self._idem_key(card.card_id),
            expected_status,
            card.model_dump_json(),
            idempotency_key or "",
            str(ttl),
        )
        return int(result) == 1

    async def resolve_pending(
        self,
        card: HITLCardView,
        *,
        expected_status: str = "pending",
        idempotency_key: str,
    ) -> bool:
        """Lua CAS: write resolved card only if stored status is still pending."""
        return await self.compare_and_set(
            card,
            expected_status=expected_status,
            idempotency_key=idempotency_key,
        )

    async def get(self, card_id: str) -> HITLCardView | None:
        """Читает карточку из Redis."""
        raw = await self._client.get(self._card_key(card_id))
        if raw is None:
            return None
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        return HITLCardView.model_validate_json(text)

    async def get_idempotency_key(self, card_id: str) -> str | None:
        """Читает idempotency key успешного ответа."""
        raw = await self._client.get(self._idem_key(card_id))
        if raw is None:
            return None
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    async def list_cards(self) -> list[HITLCardView]:
        """SCAN всех карточек для TTL sweep."""
        pattern = f"{self._prefix}{_CARD_SUFFIX}:*"
        cards: list[HITLCardView] = []
        async for key in self._client.scan_iter(match=pattern, count=100):
            raw = await self._client.get(key)
            if raw is None:
                continue
            text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            cards.append(HITLCardView.model_validate_json(text))
        return cards
