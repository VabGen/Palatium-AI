# src/palatium_ai/infrastructure/blob/minio_adapter.py

"""MinIO / S3-compatible BlobStorePort.

The MinIO SDK is synchronous, so every call is dispatched through
``asyncio.to_thread`` — a blocking call inside ``async def`` would stall the whole
graph's event loop (050).

The SDK is imported lazily: it lives in the optional ``attachments`` extra, and a
missing package must produce a clear provisioning error at wiring time rather than
an ImportError at module import (000).
"""

from __future__ import annotations

import asyncio
import contextlib

from datetime import timedelta
from typing import TYPE_CHECKING

from palatium_ai.domain.ports.blob_store import BlobNotFoundError, BlobStat

if TYPE_CHECKING:
    from minio import Minio


def resolve_public_endpoint(value: str | None, *, fallback_secure: bool) -> tuple[str, bool] | None:
    """Normalise ``ATTACHMENTS_MINIO_PUBLIC_ENDPOINT`` into ``(host:port, secure)``.

    Accepts a bare ``host:port`` (inherits the connection's scheme) or a full
    ``http(s)://host[:port]`` URL, because the public address is the one a human
    types and the scheme there is what decides whether the browser uploads over
    TLS. Note ``minio:9000`` must NOT be read as the scheme ``minio``, so only a
    literal ``://`` marks a URL.

    Returns ``None`` when unset, so the caller keeps using the connection endpoint.
    """
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if "://" in candidate:
        scheme, _, rest = candidate.partition("://")
        if scheme not in {"http", "https"}:
            msg = f"ATTACHMENTS_MINIO_PUBLIC_ENDPOINT scheme must be http or https, got {scheme!r}"
            raise ValueError(msg)
        host = rest.split("/", 1)[0]
        if not host:
            msg = f"ATTACHMENTS_MINIO_PUBLIC_ENDPOINT has no host: {value!r}"
            raise ValueError(msg)
        return host, scheme == "https"
    if "/" in candidate:
        msg = f"ATTACHMENTS_MINIO_PUBLIC_ENDPOINT must be host:port or http(s)://host[:port], got {value!r}"
        raise ValueError(msg)
    return candidate, fallback_secure


class MinIOAdapter:
    """BlobStorePort backed by MinIO/S3."""

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
        region: str = "us-east-1",
        public_endpoint: str | None = None,
    ) -> None:
        try:
            from minio import Minio as _Minio
        except ImportError as exc:  # pragma: no cover - depends on install extras
            msg = (
                "minio package is required for ATTACHMENTS_BLOB_BACKEND=minio; "
                "install it with `poetry install --with attachments`"
            )
            raise RuntimeError(msg) from exc
        self._client: Minio = _Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region,
        )
        # Presigning is local signature computation, not I/O, so the presign client
        # may name a host only the *browser* can resolve. This split is required, not
        # cosmetic: in a compose network the API reaches the store as ``minio:9000``
        # while the user's browser resolves ``127.0.0.1:9000``, and SigV4 signs the
        # Host header — so the finished URL cannot be rewritten afterwards. Without
        # the split the API hands out an unreachable URL and every direct upload dies
        # at the PUT, leaving the row stuck in ``pending``.
        public = resolve_public_endpoint(public_endpoint, fallback_secure=secure)
        self._presign_client: Minio = (
            self._client
            if public is None
            else _Minio(
                public[0],
                access_key=access_key,
                secret_key=secret_key,
                secure=public[1],
                region=region,
            )
        )
        self._public_endpoint = None if public is None else public[0]
        self._bucket = bucket

    @property
    def public_endpoint(self) -> str | None:
        """The host the browser-facing URLs are signed for; ``None`` = connection host."""
        return self._public_endpoint

    async def ensure_bucket(self) -> bool:
        """Create the bucket when missing; returns True when it already existed."""
        return await asyncio.to_thread(self._ensure_bucket_sync)

    def _ensure_bucket_sync(self) -> bool:
        if self._client.bucket_exists(self._bucket):
            return True
        self._client.make_bucket(self._bucket)
        return False

    async def presigned_put_url(self, key: str, *, content_type: str, expires_seconds: int) -> str:
        """Presign a PUT for the **browser**, signed against the public endpoint.

        Note the signature does not cover ``Content-Type`` for a plain PUT, so the
        declared media type is *not* enforced by the URL: ``stat`` re-reads the
        stored object and policy is decided on that server-side truth (020).
        """
        return await asyncio.to_thread(
            self._presign_client.presigned_put_object,
            self._bucket,
            key,
            expires=timedelta(seconds=expires_seconds),
        )

    async def presigned_get_url(self, key: str, *, expires_seconds: int) -> str:
        """Presign a GET for the browser; same host rule as the PUT."""
        return await asyncio.to_thread(
            self._presign_client.presigned_get_object,
            self._bucket,
            key,
            expires=timedelta(seconds=expires_seconds),
        )

    async def stat(self, key: str) -> BlobStat | None:
        """Return stored size/content type, or None when the key is absent."""
        try:
            result = await asyncio.to_thread(self._client.stat_object, self._bucket, key)
        except Exception as exc:
            if self._is_not_found(exc):
                return None
            raise
        size = result.size
        if size is None:  # pragma: no cover - stat_object always reports a size
            msg = f"MinIO stat for {key!r} returned no size"
            raise RuntimeError(msg)
        return BlobStat(
            key=key,
            size_bytes=int(size),
            content_type=getattr(result, "content_type", None),
        )

    async def read_bytes(self, key: str) -> bytes:
        """Read an object fully, releasing the connection even on failure."""
        try:
            return await asyncio.to_thread(self._read_bytes_sync, key)
        except Exception as exc:
            if self._is_not_found(exc):
                raise BlobNotFoundError(key) from exc
            raise

    def _read_bytes_sync(self, key: str) -> bytes:
        response = self._client.get_object(self._bucket, key)
        try:
            return bytes(response.read())
        finally:
            response.close()
            with contextlib.suppress(Exception):
                response.release_conn()

    async def write_bytes(self, key: str, data: bytes, *, content_type: str) -> None:
        """Store derived artifacts (extracted text)."""
        await asyncio.to_thread(self._write_bytes_sync, key, data, content_type)

    def _write_bytes_sync(self, key: str, data: bytes, content_type: str) -> None:
        from io import BytesIO

        self._client.put_object(
            self._bucket,
            key,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    async def exists(self, key: str) -> bool:
        """Whether the object exists."""
        return await self.stat(key) is not None

    async def delete(self, key: str) -> None:
        """Remove an object; a missing key is not an error."""
        await asyncio.to_thread(self._remove_sync, key)

    def _remove_sync(self, key: str) -> None:
        with contextlib.suppress(Exception):
            self._client.remove_object(self._bucket, key)

    @staticmethod
    def _is_not_found(exc: Exception) -> bool:
        """Recognise S3 NoSuchKey/NoSuchObject without importing minio at module scope."""
        code = getattr(exc, "code", None)
        if code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
            return True
        text = str(exc)
        return "NoSuchKey" in text or "does not exist" in text
