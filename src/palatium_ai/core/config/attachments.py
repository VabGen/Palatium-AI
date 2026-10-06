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
    max_chunk_bytes: int = Field(
        default=8 * 1024 * 1024,
        ge=64 * 1024,
        le=64 * 1024 * 1024,
        validation_alias="ATTACHMENTS_MAX_CHUNK_BYTES",
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

    # Image OCR. Images carry no text layer, so the only way to make them usable in
    # a text pipeline is OCR and/or a vision model. ``disabled`` means no image parser
    # is wired (intake refuses image/*). ``auto`` (default) is progressive 2026:
    # Tesseract first, Vision escalate on failure/low quality when a model is set.
    # ``gateway`` always prefers Vision; ``tesseract`` is local-only / air-gapped.
    image_ocr_backend: Literal["disabled", "auto", "gateway", "tesseract"] = Field(
        default="auto",
        validation_alias="ATTACHMENTS_IMAGE_OCR_BACKEND",
    )
    #: Gateway model alias for the vision model (e.g. ``tier-vision``). Must exist in
    #: the gateway's ``model_list``; this is a routing name, not an upstream API id.
    #: Required for ``gateway``; optional for ``auto`` (Vision escalate when present).
    image_ocr_model: str | None = Field(default=None, validation_alias="ATTACHMENTS_IMAGE_OCR_MODEL")
    #: Upper bound on the original image bytes sent to the model. The intake cap is far
    #: larger than any sane model payload, so a raw 50 MiB upload must not be forwarded.
    image_ocr_max_bytes: int = Field(
        default=8 * 1024 * 1024,
        ge=64 * 1024,
        le=64 * 1024 * 1024,
        validation_alias="ATTACHMENTS_IMAGE_OCR_MAX_BYTES",
    )
    image_ocr_timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
        le=600.0,
        validation_alias="ATTACHMENTS_IMAGE_OCR_TIMEOUT_SECONDS",
        description="Vision OCR call timeout (P2.16); upload pipeline only — chat requires ready ids.",
    )
    #: Escalate to Vision when local OCR yields fewer than this many chars (G14 progressive).
    ocr_min_chars: int = Field(
        default=12,
        ge=1,
        le=10_000,
        validation_alias="ATTACHMENTS_OCR_MIN_CHARS",
    )
    #: Escalate when printable ratio of OCR text is below this (0–1).
    ocr_min_printable_ratio: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        validation_alias="ATTACHMENTS_OCR_MIN_PRINTABLE_RATIO",
    )
    #: Escalate when Tesseract mean word confidence is below this (0–100).
    #: Catches Latin gibberish from Cyrillic handwriting that still looks "printable".
    ocr_min_confidence: float = Field(
        default=55.0,
        ge=0.0,
        le=100.0,
        validation_alias="ATTACHMENTS_OCR_MIN_CONFIDENCE",
    )
    #: Average chars/page below this → treat PDF as scan and route to OCR.
    pdf_min_avg_chars_per_page: int = Field(
        default=200,
        ge=1,
        le=10_000,
        validation_alias="ATTACHMENTS_PDF_MIN_AVG_CHARS_PER_PAGE",
    )
    #: Absolute path to the ``tesseract`` binary when it is not on ``PATH``
    #: (Windows portable install, custom container layout). Empty → system PATH.
    tesseract_cmd: str | None = Field(
        default=None,
        validation_alias="ATTACHMENTS_TESSERACT_CMD",
    )
    #: Cap on PDF pages sent to the vision model (cost/latency; G14).
    pdf_vision_max_pages: int = Field(
        default=20,
        ge=1,
        le=100,
        validation_alias="ATTACHMENTS_PDF_VISION_MAX_PAGES",
    )
    #: When text layer is usable, still VLM pages that embed images/charts (G14).
    pdf_figure_enrichment: bool = Field(
        default=True,
        validation_alias="ATTACHMENTS_PDF_FIGURE_ENRICHMENT",
    )
    #: Soft cap on figure-enrichment vision calls per document.
    pdf_figure_max_pages: int = Field(
        default=8,
        ge=0,
        le=50,
        validation_alias="ATTACHMENTS_PDF_FIGURE_MAX_PAGES",
    )
    #: Attachment analysis sandbox (G15 ADA). ``disabled`` fail-closed; ``local``
    #: runs deterministic dataframe summaries on CSV/XLSX with HITL before use.
    analysis_backend: Literal["disabled", "local"] = Field(
        default="disabled",
        validation_alias="ATTACHMENTS_ANALYSIS_BACKEND",
    )
    #: Extracted-text PII tiers (G06). ``tag`` records ``contains_pii`` only;
    #: ``mask`` redacts detectors in ``safe_text``; ``reject`` refuses intake.
    pii_policy: Literal["tag", "mask", "reject"] = Field(
        default="tag",
        validation_alias="ATTACHMENTS_PII_POLICY",
    )

    @field_validator(
        "minio_public_endpoint",
        "minio_access_key",
        "minio_secret_key",
        "image_ocr_model",
        "tesseract_cmd",
        mode="before",
    )
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

    @model_validator(mode="after")
    def _image_ocr_backend_requires_model(self) -> Self:
        """Gateway-only mode without a model would silently reject every image."""
        if self.image_ocr_backend != "gateway":
            return self
        if not (self.image_ocr_model or "").strip():
            msg = "ATTACHMENTS_IMAGE_OCR_BACKEND=gateway requires ATTACHMENTS_IMAGE_OCR_MODEL"
            raise ValueError(msg)
        return self
