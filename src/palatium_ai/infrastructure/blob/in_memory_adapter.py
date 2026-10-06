# src/palatium_ai/infrastructure/blob/in_memory_adapter.py

"""Process-local BlobStorePort (unit tests and single-process dev only).

The "presigned" URLs are inert placeholders: there is no HTTP surface behind
them, so tests drive uploads through ``put_direct`` instead of a real PUT. The
wiring layer refuses this backend outside local/test environments (020).
"""

from __future__ import annotations

import asyncio

from palatium_ai.domain.ports.blob_store import BlobNotFoundError, BlobStat


class InMemoryBlobStore:
    """Dict-backed object store; every object lives only in this process."""

    def __init__(self, *, bucket: str = "palatium-attachments") -> None:
        self._bucket = bucket
        self._lock = asyncio.Lock()
        self._objects: dict[str, tuple[bytes, str]] = {}

    async def presigned_put_url(self, key: str, *, content_type: str, expires_seconds: int) -> str:
        """Return a placeholder upload URL (no real HTTP endpoint exists)."""
        return f"memory://{self._bucket}/{key}?expires={expires_seconds}&signature=in-memory"

    async def presigned_get_url(self, key: str, *, expires_seconds: int) -> str:
        """Return a placeholder download URL."""
        return f"memory://{self._bucket}/{key}?expires={expires_seconds}&signature=in-memory"

    async def stat(self, key: str) -> BlobStat | None:
        """Return stored size/content type, or None when absent."""
        async with self._lock:
            stored = self._objects.get(key)
        if stored is None:
            return None
        data, content_type = stored
        return BlobStat(key=key, size_bytes=len(data), content_type=content_type)

    async def read_bytes(self, key: str) -> bytes:
        """Read an object fully."""
        async with self._lock:
            stored = self._objects.get(key)
        if stored is None:
            raise BlobNotFoundError(key)
        return stored[0]

    async def write_bytes(self, key: str, data: bytes, *, content_type: str) -> None:
        """Store bytes (used for both simulated uploads and derived artifacts)."""
        async with self._lock:
            self._objects[key] = (data, content_type)

    async def exists(self, key: str) -> bool:
        """Whether the key is present."""
        async with self._lock:
            return key in self._objects

    async def delete(self, key: str) -> None:
        """Remove an object; a missing key is not an error."""
        async with self._lock:
            self._objects.pop(key, None)

    async def put_direct(self, key: str, data: bytes, *, content_type: str) -> None:
        """Test/dev helper that stands in for the client's presigned PUT."""
        await self.write_bytes(key, data, content_type=content_type)

    async def keys(self) -> tuple[str, ...]:
        """All stored keys (test introspection only)."""
        async with self._lock:
            return tuple(self._objects)
