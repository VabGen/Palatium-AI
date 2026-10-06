# src/palatium_ai/infrastructure/blob/factory.py

"""BlobStorePort factory (070: fail closed on a half-configured store)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from palatium_ai.core.logging import logger
from palatium_ai.domain.ports.blob_store import BlobStorePort
from palatium_ai.infrastructure.blob.filesystem_adapter import FilesystemBlobStore
from palatium_ai.infrastructure.blob.in_memory_adapter import InMemoryBlobStore
from palatium_ai.infrastructure.blob.minio_adapter import MinIOAdapter

if TYPE_CHECKING:
    from palatium_ai.core.config.settings import Settings

_NON_LOCAL_ENVIRONMENTS = frozenset({"staging", "production"})


def build_blob_store(settings: Settings) -> BlobStorePort:
    """Select the blob backend; refuse an in-process store outside local/test."""
    config = settings.attachments
    if config.blob_backend == "minio":
        if settings.app.environment in _NON_LOCAL_ENVIRONMENTS and not config.minio_secure:
            msg = (
                f"ATTACHMENTS_MINIO_SECURE must be true in {settings.app.environment!r}: "
                "S3 credentials and object bytes would otherwise travel in plaintext (020)"
            )
            raise RuntimeError(msg)
        access_key = config.minio_access_key.get_secret_value() if config.minio_access_key is not None else ""
        secret_key = config.minio_secret_key.get_secret_value() if config.minio_secret_key is not None else ""
        adapter = MinIOAdapter(
            endpoint=config.minio_endpoint,
            access_key=access_key,
            secret_key=secret_key,
            bucket=config.minio_bucket,
            secure=config.minio_secure,
            region=config.minio_region,
            public_endpoint=config.minio_public_endpoint,
        )
        logger.info(
            "BlobStorePort: MinIO",
            endpoint=config.minio_endpoint,
            bucket=config.minio_bucket,
            secure=config.minio_secure,
            # A silent fallback here is the failure this knob exists to prevent: the
            # browser would be handed a URL signed for the in-cluster hostname.
            presign_endpoint=adapter.public_endpoint or config.minio_endpoint,
        )
        return adapter

    if config.blob_backend == "filesystem":
        if settings.app.environment in _NON_LOCAL_ENVIRONMENTS:
            msg = (
                f"ATTACHMENTS_BLOB_BACKEND=filesystem is not allowed in {settings.app.environment!r}: "
                "a local directory is not shared between replicas — use minio"
            )
            raise RuntimeError(msg)
        logger.warning(
            "BlobStorePort: local filesystem (dev only)",
            root=config.filesystem_root,
        )
        return FilesystemBlobStore(root=Path(config.filesystem_root), bucket=config.minio_bucket)

    if settings.app.environment in _NON_LOCAL_ENVIRONMENTS:
        msg = (
            f"ATTACHMENTS_BLOB_BACKEND=memory is not allowed in {settings.app.environment!r}: "
            "uploads would not survive a restart or a second replica"
        )
        raise RuntimeError(msg)
    logger.warning(
        "BlobStorePort: in-memory (dev/test only)",
        environment=settings.app.environment,
    )
    return InMemoryBlobStore(bucket=config.minio_bucket)
