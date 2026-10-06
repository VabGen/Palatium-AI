# src/palatium_ai/domain/ports/blob_store.py

"""Port for binary object storage (MinIO/S3 and the in-memory test double)."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class BlobNotFoundError(LookupError):
    """Raised when a requested object key does not exist.

    Domain-level so a missing object never surfaces as a driver-specific
    exception (``S3Error``/``NoSuchKey``) in application or presentation code.
    """


class BlobStat(BaseModel):
    """Server-side truth about a stored object.

    The client declares size and media type at intake, but a client can lie, so
    the size and content type that decide policy must come from storage (020).
    """

    model_config = {"frozen": True}

    key: str = Field(min_length=1, max_length=512)
    size_bytes: int = Field(ge=0)
    content_type: str | None = Field(default=None, max_length=128)


class BlobStorePort(Protocol):
    """Async facade over an object store; adapters wrap their blocking SDK (050)."""

    async def presigned_put_url(self, key: str, *, content_type: str, expires_seconds: int) -> str:
        """Return a time-boxed URL the client uploads to directly."""
        ...

    async def presigned_get_url(self, key: str, *, expires_seconds: int) -> str:
        """Return a time-boxed download URL for a stored object."""
        ...

    async def stat(self, key: str) -> BlobStat | None:
        """Return stored size/content type, or None when the key was never uploaded."""
        ...

    async def read_bytes(self, key: str) -> bytes:
        """Read an object fully; callers must respect the intake size cap."""
        ...

    async def write_bytes(self, key: str, data: bytes, *, content_type: str) -> None:
        """Store an object under ``key``.

        Used for derived artifacts (extracted text) and for the original blob when
        the API proxies an upload — the presigned PUT path writes the original
        straight to the store instead. Overwriting a key is a no-op for policy:
        the service only accepts a write while the row is still pre-pipeline.
        """
        ...

    async def exists(self, key: str) -> bool:
        """Verify a claimed upload actually landed before trusting the client."""
        ...

    async def delete(self, key: str) -> None:
        """Remove an object; deleting a missing key is not an error."""
        ...
