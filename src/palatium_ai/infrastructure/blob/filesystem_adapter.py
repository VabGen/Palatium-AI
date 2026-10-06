# src/palatium_ai/infrastructure/blob/filesystem_adapter.py

"""Local-filesystem BlobStorePort for single-machine dev (020).

Two real problems this solves for a dev laptop, without adding a service:

* the in-process store loses every object as soon as the API runs with more than one
  worker (``UVICORN_WORKERS=2`` in ``env/.env.example``), so ``init`` and ``complete``
  can land in different processes and the upload looks lost; and
* the upstream MinIO images are no longer published on Docker Hub, so there is no
  zero-config S3 container to point at.

Objects live under one configured root and keys are confined to it. The wiring layer
refuses this backend outside local/test environments: a directory is not a substitute
for object storage once more than one replica writes to it.

Like the in-memory store, the "presigned" URLs are inert placeholders — a directory
has no HTTP surface — so the client uploads through
``PUT /api/attachments/{id}/content`` instead (see ``docs/runbook.md`` §16.4).
"""

from __future__ import annotations

import asyncio

from pathlib import Path

from palatium_ai.domain.ports.blob_store import BlobNotFoundError, BlobStat

#: Sidecar holding the object's media type; ``stat`` reports it, policy does not use it.
_META_SUFFIX = ".content-type"
#: In-flight write target. Renamed onto the final name so readers never see a torn file.
_PART_SUFFIX = ".part"


class FilesystemBlobStore:
    """Directory-backed object store: one file per key under ``root``."""

    def __init__(self, *, root: Path, bucket: str = "palatium-attachments") -> None:
        self._root = Path(root)
        self._bucket = bucket

    async def presigned_put_url(self, key: str, *, content_type: str, expires_seconds: int) -> str:
        """Placeholder upload URL; the scheme tells the client to use the API instead."""
        return f"filesystem://{self._bucket}/{key}?expires={expires_seconds}&signature=filesystem"

    async def presigned_get_url(self, key: str, *, expires_seconds: int) -> str:
        """Placeholder download URL."""
        return f"filesystem://{self._bucket}/{key}?expires={expires_seconds}&signature=filesystem"

    async def stat(self, key: str) -> BlobStat | None:
        """Return stored size/content type, or None when the key was never written."""
        return await asyncio.to_thread(self._stat_sync, key)

    def _stat_sync(self, key: str) -> BlobStat | None:
        path = self._path_for(key)
        if not path.is_file():
            return None
        return BlobStat(
            key=key,
            size_bytes=path.stat().st_size,
            content_type=self._read_content_type(path),
        )

    async def read_bytes(self, key: str) -> bytes:
        """Read an object fully; a missing key is a typed port error (035)."""
        return await asyncio.to_thread(self._read_sync, key)

    def _read_sync(self, key: str) -> bytes:
        try:
            return self._path_for(key).read_bytes()
        except FileNotFoundError as exc:
            raise BlobNotFoundError(key) from exc

    async def write_bytes(self, key: str, data: bytes, *, content_type: str) -> None:
        """Store bytes atomically: a reader never observes a half-written object."""
        await asyncio.to_thread(self._write_sync, key, data, content_type)

    def _write_sync(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        part = Path(f"{path}{_PART_SUFFIX}")
        part.write_bytes(data)
        # Path.replace is an atomic rename on the same filesystem, so ``stat`` can never
        # report a truncated size while the pipeline is deciding to admit the file (020).
        part.replace(path)
        Path(f"{path}{_META_SUFFIX}").write_text(content_type, encoding="utf-8")

    async def exists(self, key: str) -> bool:
        """Whether the key is present."""
        return await asyncio.to_thread(lambda: self._path_for(key).is_file())

    async def delete(self, key: str) -> None:
        """Remove an object; deleting a missing key is not an error."""
        await asyncio.to_thread(self._delete_sync, key)

    def _delete_sync(self, key: str) -> None:
        path = self._path_for(key)
        for candidate in (path, Path(f"{path}{_META_SUFFIX}")):
            try:
                candidate.unlink()
            except FileNotFoundError:
                continue

    def _read_content_type(self, path: Path) -> str | None:
        meta = Path(f"{path}{_META_SUFFIX}")
        if not meta.is_file():
            return None
        return meta.read_text(encoding="utf-8").strip() or None

    def _path_for(self, key: str) -> Path:
        """Resolve ``key`` under the root, refusing anything that escapes it (020).

        ``Path.resolve`` also collapses symlinked components, so a link planted inside
        the root cannot be used to read or overwrite files outside it. An absolute key
        is rejected for the same reason: ``root / '/etc/passwd'`` is ``/etc/passwd``.
        """
        root = self._root.resolve()
        candidate = (root / key).resolve()
        if candidate != root and root not in candidate.parents:
            msg = f"blob key escapes the storage root: {key!r}"
            raise ValueError(msg)
        return candidate


__all__ = ["FilesystemBlobStore"]
