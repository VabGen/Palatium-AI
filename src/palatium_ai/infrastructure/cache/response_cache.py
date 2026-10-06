# src/palatium_ai/infrastructure/cache/response_cache.py

"""L1 response cache adapters (Redis + in-memory for tests/dev)."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING

from palatium_ai.core.logging import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

_MAX_VALUE_CHARS = 256_000


@dataclass
class _MemoryEntry:
    value: str
    expires_at: float


@dataclass
class InMemoryResponseCache:
    """Process-local L1 cache with TTL (tests / Redis-less smoke)."""

    _entries: dict[str, _MemoryEntry] = field(default_factory=dict)
    _max_entries: int = 1_024

    async def get(self, key: str) -> str | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= monotonic():
            self._entries.pop(key, None)
            return None
        return entry.value

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        if len(self._entries) >= self._max_entries and key not in self._entries:
            # Drop arbitrary oldest-ish key (insertion order) to bound memory (080).
            self._entries.pop(next(iter(self._entries)), None)
        self._entries[key] = _MemoryEntry(
            value=value[:_MAX_VALUE_CHARS],
            expires_at=monotonic() + float(ttl_seconds),
        )


@dataclass(frozen=True, slots=True)
class RedisResponseCache:
    """Redis-backed L1 response cache."""

    _redis: Redis

    async def get(self, key: str) -> str | None:
        try:
            raw = await self._redis.get(key)
        except Exception as exc:
            logger.warning("response_cache.redis_get_failed", error=str(exc))
            return None
        if raw is None:
            return None
        if isinstance(raw, bytes):
            return raw.decode("utf-8")
        return str(raw)

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        try:
            await self._redis.set(key, value[:_MAX_VALUE_CHARS], ex=ttl_seconds)
        except Exception as exc:
            logger.warning("response_cache.redis_set_failed", error=str(exc))
