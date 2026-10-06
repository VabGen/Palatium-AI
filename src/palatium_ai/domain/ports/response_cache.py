# src/palatium_ai/domain/ports/response_cache.py

"""Port for L1 exact-match response cache (Redis or in-memory)."""

from __future__ import annotations

from typing import Protocol


class ResponseCachePort(Protocol):
    """Byte/string get-set with TTL (080: bounded via TTL, not unbounded growth)."""

    async def get(self, key: str) -> str | None:
        """Return cached payload or None on miss."""
        ...

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        """Store payload with TTL; overwrites existing."""
        ...
