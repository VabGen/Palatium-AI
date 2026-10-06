# src/palatium_ai/core/config/attachments.py

"""Настройки вложений (attachments): хранилище, сканер, лимиты интейка.

Лимиты здесь — плоские значения, а не ``AttachmentLimits``: ``core`` не имеет
права импортировать ``domain`` (000, scripts/check_import_layers.py). Сборка
доменного value object — задача composition root (application/wiring.py).
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator

from .base import BaseConfig


class AttachmentConfig(BaseConfig):
    """Blob store + AV scanner + intake limits for the attachment pipeline."""

    enabled: bool = Field(default=False, validation_alias="ATTACHMENTS_ENABLED")

    # Blob storage: ``minio`` is the S3-compatible production/dev backend;
    # ``filesystem`` is a single-machine dev store (durable across restarts and
    # workers); ``memory`` exists for unit tests and single-process dev only.
    # ``memory``/``filesystem`` are refused outside local/test by the wiring layer (020).
    blob_backend: Literal["memory", "minio", "filesystem"] = Field(
        default="memory",
        validation_alias="ATTACHMENTS_BLOB_BACKEND",
    )
    filesystem_root: str = Field(
        default=".local/attachments",
        validation_alias="ATTACHMENTS_FILESYSTEM_ROOT",
    )
    minio_endpoint: str = Field(default="localhost:9000", validation_alias="ATTACHMENTS_MINIO_ENDPOINT")
    # Address the *browser* uses for the presigned PUT. Required whenever the store is
    # reachable under a different name from inside the API process than from the user's
    # browser (the compose network calls it ``minio:9000``, the browser calls it
    # ``127.0.0.1:9000``). SigV4 signs the Host header, so the URL cannot be rewritten
    # after signing — the API must presign against this address instead (020).
    minio_public_endpoint: str | None = Field(
        default=None,
        validation_alias="ATTACHMENTS_MINIO_PUBLIC_ENDPOINT",
    )
    minio_access_key: SecretStr | None = Field(default=None, validation_alias="ATTACHMENTS_MINIO_ACCESS_KEY")
    minio_secret_key: SecretStr | None = Field(default=None, validation_alias="ATTACHMENTS_MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="palatium-attachments", validation_alias="ATTACHMENTS_MINIO_BUCKET")
    minio_secure: bool = Field(default=False, validation_alias="ATTACHMENTS_MINIO_SECURE")
    minio_region: str = Field(default="us-east-1", validation_alias="ATTACHMENTS_MINIO_REGION")

    # Malware verdict before any LLM sees a file. ``disabled`` is refused
    # outside local/test environments (020: files are low-trust input).
    scanner_backend: Literal["disabled", "clamav"] = Field(
        default="disabled",
        validation_alias="ATTACHMENTS_SCANNER_BACKEND",
    )
    clamav_host: str = Field(default="localhost", validation_alias="ATTACHMENTS_CLAMAV_HOST")
    clamav_port: int = Field(default=3310, ge=1, le=65535, validation_alias="ATTACHMENTS_CLAMAV_PORT")
    clamav_timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
        le=300.0,
        validation_alias="ATTACHMENTS_CLAMAV_TIMEOUT_SECONDS",
    )

    # Intake limits. Bounds mirror AttachmentLimits; the domain model re-validates.
    max_size_bytes: int = Field(
        default=50 * 1024 * 1024,
        ge=1024,
        le=512 * 1024 * 1024,
        validation_alias="ATTACHMENTS_MAX_SIZE_BYTES",
    )
    max_attachments_per_turn: int = Field(
        default=5,
        ge=1,
        le=50,
        validation_alias="ATTACHMENTS_MAX_PER_TURN",
    )
    max_filename_chars: int = Field(
        default=200,
        ge=16,
        le=255,
        validation_alias="ATTACHMENTS_MAX_FILENAME_CHARS",
    )
    presigned_url_ttl_seconds: int = Field(
        default=900,
        ge=60,
        le=3600,
        validation_alias="ATTACHMENTS_PRESIGNED_TTL_SECONDS",
    )
    # Must outlive the thread, otherwise follow-ups on a live dialog fail (W1 policy).
    attach_ttl_seconds: int = Field(
        default=7 * 24 * 3600,
        ge=300,
        validation_alias="ATTACHMENTS_ATTACH_TTL_SECONDS",
    )
    index_retention_days: int = Field(
        default=365,
        ge=1,
        le=3650,
        validation_alias="ATTACHMENTS_INDEX_RETENTION_DAYS",
    )
    # Rows reclaimed per retention pass; bounds mirror AttachmentLimits (010).
    sweep_batch_size: int = Field(
        default=200,
        ge=1,
        le=5000,
        validation_alias="ATTACHMENTS_SWEEP_BATCH_SIZE",
    )
    max_parsed_chars: int = Field(
        default=2_000_000,
        ge=1000,
        le=20_000_000,
        validation_alias="ATTACHMENTS_MAX_PARSED_CHARS",
    )
    max_parsed_pages: int = Field(
        default=500,
        ge=1,
        le=10_000,
        validation_alias="ATTACHMENTS_MAX_PARSED_PAGES",
    )

    @field_validator("minio_public_endpoint", "minio_access_key", "minio_secret_key", mode="before")
    @classmethod
    def _empty_string_as_none(cls, value: object) -> object:
        """An unanswered env template placeholder is *absent*, not a value (020)."""
        if value is None or value == "":
            return None
        return value

    @model_validator(mode="after")
    def _minio_backend_requires_credentials(self) -> Self:
        """Fail at startup, not on the first upload (020: no half-configured stores)."""
        if self.blob_backend != "minio":
            return self
        if self.minio_access_key is None or self.minio_secret_key is None:
            msg = (
                "ATTACHMENTS_BLOB_BACKEND=minio requires ATTACHMENTS_MINIO_ACCESS_KEY and ATTACHMENTS_MINIO_SECRET_KEY"
            )
            raise ValueError(msg)
        if not self.minio_bucket.strip():
            msg = "ATTACHMENTS_MINIO_BUCKET must not be empty"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _clamav_backend_requires_host(self) -> Self:
        if self.scanner_backend != "clamav":
            return self
        if not self.clamav_host.strip():
            msg = "ATTACHMENTS_SCANNER_BACKEND=clamav requires ATTACHMENTS_CLAMAV_HOST"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _filesystem_backend_requires_root(self) -> Self:
        """Fail at startup, not on the first upload (020: no half-configured stores)."""
        if self.blob_backend != "filesystem":
            return self
        if not self.filesystem_root.strip():
            msg = "ATTACHMENTS_BLOB_BACKEND=filesystem requires ATTACHMENTS_FILESYSTEM_ROOT"
            raise ValueError(msg)
        return self
