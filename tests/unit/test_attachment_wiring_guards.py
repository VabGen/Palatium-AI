"""W2 wiring guards: configuration validation + fail-closed backend selection (020).

The attachment pipeline treats uploads as low-trust input, so the dangerous
backends (in-process blob store, disabled AV) must be impossible in staging and
production, and a half-configured store must fail at startup, not on first upload.

These tests use a stub settings object instead of constructing ``Settings``: the
real aggregate pulls every sub-config (and therefore the whole ``env/.env``) into
the test, which makes the assertions depend on the developer's local environment
rather than on the guard being tested.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from palatium_ai.application.wiring import build_attachment_ports
from palatium_ai.core.config.attachments import AttachmentConfig
from palatium_ai.core.config.settings import Settings
from palatium_ai.domain.ports.blob_store import BlobStorePort
from palatium_ai.infrastructure.blob.factory import build_blob_store
from palatium_ai.infrastructure.blob.filesystem_adapter import FilesystemBlobStore
from palatium_ai.infrastructure.blob.in_memory_adapter import InMemoryBlobStore
from palatium_ai.infrastructure.blob.minio_adapter import MinIOAdapter
from palatium_ai.infrastructure.parsing.factory import build_document_parser
from palatium_ai.infrastructure.scanning.factory import build_malware_scanner
from palatium_ai.infrastructure.scanning.noop_scanner import DisabledScanner

if TYPE_CHECKING:
    from palatium_ai.core.config.settings import Settings as SettingsType


def _config(**overrides: object) -> AttachmentConfig:
    """Hermetic config: ignore env/.env so the test asserts defaults, not the host."""
    return AttachmentConfig(_env_file=None, **overrides)  # type: ignore[arg-type]


def _settings(*, environment: str = "local", **attachment_overrides: object) -> SettingsType:
    """Minimal stand-in exposing only what the wiring factories read."""
    stub: Any = SimpleNamespace(
        app=SimpleNamespace(environment=environment),
        attachments=_config(**attachment_overrides),
    )
    return cast("SettingsType", stub)


def test_attachment_config_is_disabled_by_default() -> None:
    assert _config().enabled is False


def test_minio_backend_requires_credentials() -> None:
    """Fail at startup: a MinIO backend without keys would 500 on every upload."""
    with pytest.raises(ValueError, match="ATTACHMENTS_MINIO_ACCESS_KEY"):
        _config(blob_backend="minio")


def test_minio_backend_accepts_complete_credentials() -> None:
    config = _config(
        blob_backend="minio",
        minio_access_key="key",
        minio_secret_key="secret",
        minio_bucket="bucket",
    )
    assert config.blob_backend == "minio"
    assert config.minio_access_key is not None


def test_empty_minio_secret_is_normalised_to_none() -> None:
    """An empty env var must not masquerade as a configured secret (020)."""
    config = _config(minio_access_key="", minio_secret_key="")
    assert config.minio_access_key is None
    assert config.minio_secret_key is None


def test_minio_bucket_must_not_be_blank() -> None:
    with pytest.raises(ValueError, match="ATTACHMENTS_MINIO_BUCKET"):
        _config(blob_backend="minio", minio_access_key="k", minio_secret_key="s", minio_bucket="  ")


def test_minio_public_endpoint_is_optional_and_empty_means_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset/blank must stay ``None`` so the adapter presigns against the connection host."""
    # conftest seeds os.environ from env/.env.example, so "unset" must be forced here —
    # otherwise the test asserts on the ambient default instead of the absent case.
    monkeypatch.delenv("ATTACHMENTS_MINIO_PUBLIC_ENDPOINT", raising=False)
    assert _config().minio_public_endpoint is None
    assert _config(minio_public_endpoint="").minio_public_endpoint is None


def test_minio_public_endpoint_survives_into_the_adapter() -> None:
    """A dropped value would send the browser an in-cluster hostname that it cannot resolve."""
    pytest.importorskip("minio")
    store = build_blob_store(
        _settings(
            blob_backend="minio",
            minio_access_key="key",
            minio_secret_key="secret",
            minio_endpoint="minio:9000",
            minio_public_endpoint="http://127.0.0.1:9001",
        )
    )

    assert isinstance(store, MinIOAdapter)
    assert store.public_endpoint == "127.0.0.1:9001"


def test_blob_factory_leaves_the_presign_host_alone_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("minio")
    monkeypatch.delenv("ATTACHMENTS_MINIO_PUBLIC_ENDPOINT", raising=False)
    store = build_blob_store(
        _settings(
            blob_backend="minio",
            minio_access_key="key",
            minio_secret_key="secret",
            minio_endpoint="minio:9000",
        )
    )

    assert isinstance(store, MinIOAdapter)
    assert store.public_endpoint is None


def test_intake_limits_have_sane_bounds() -> None:
    with pytest.raises(ValueError):
        _config(max_size_bytes=10)
    with pytest.raises(ValueError):
        _config(max_attachments_per_turn=0)


def test_retention_sweep_batch_is_bounded_and_mapped_onto_the_domain_limits() -> None:
    """The config value must reach ``AttachmentLimits`` — a silent gap is a hardcoded limit."""
    from palatium_ai.application.wiring import build_attachment_limits
    from palatium_ai.domain.attachments import DEFAULT_ATTACHMENT_LIMITS

    assert build_attachment_limits(_settings()).retention_sweep_batch == _config().sweep_batch_size
    assert DEFAULT_ATTACHMENT_LIMITS.retention_sweep_batch == _config().sweep_batch_size
    with pytest.raises(ValueError):
        _config(sweep_batch_size=0)
    with pytest.raises(ValueError):
        _config(sweep_batch_size=10_000)


def test_settings_aggregator_registers_the_attachment_config() -> None:
    """Regression guard: the sub-config must stay wired into the aggregator."""
    assert "attachments" in Settings.model_fields
    assert Settings.model_fields["attachments"].annotation is AttachmentConfig


def test_blob_factory_returns_in_memory_adapter_locally() -> None:
    assert isinstance(build_blob_store(_settings()), InMemoryBlobStore)


def test_blob_factory_returns_filesystem_adapter_locally(tmp_path: Path) -> None:
    """Durable dev store: unlike ``memory`` it survives the documented 2-worker setup."""
    store = build_blob_store(_settings(blob_backend="filesystem", filesystem_root=str(tmp_path)))

    assert isinstance(store, FilesystemBlobStore)
    assert not isinstance(store, InMemoryBlobStore)


def test_filesystem_backend_requires_a_root() -> None:
    with pytest.raises(ValueError, match="ATTACHMENTS_FILESYSTEM_ROOT"):
        _config(blob_backend="filesystem", filesystem_root="   ")


@pytest.mark.parametrize("environment", ("staging", "production"))
def test_blob_factory_refuses_filesystem_store_outside_local(environment: str, tmp_path: Path) -> None:
    """A directory is not shared between replicas — staging/production need real storage."""
    with pytest.raises(RuntimeError, match="filesystem is not allowed"):
        build_blob_store(
            _settings(
                environment=environment,
                blob_backend="filesystem",
                filesystem_root=str(tmp_path),
            )
        )


def _minio_settings(*, environment: str, secure: bool) -> SettingsType:
    return _settings(
        environment=environment,
        blob_backend="minio",
        minio_access_key="k",
        minio_secret_key="s",
        minio_bucket="bucket",
        minio_secure=secure,
    )


@pytest.mark.parametrize("environment", ("staging", "production"))
def test_minio_requires_tls_outside_local(environment: str) -> None:
    """Plaintext S3 would put the credentials and the object bytes on the wire (020)."""
    with pytest.raises(RuntimeError, match="ATTACHMENTS_MINIO_SECURE"):
        build_blob_store(_minio_settings(environment=environment, secure=False))


def test_minio_plaintext_is_tolerated_locally() -> None:
    """A dev MinIO without TLS must still be usable behind the localhost boundary."""
    pytest.importorskip("minio")
    store = build_blob_store(_minio_settings(environment="local", secure=False))
    assert not isinstance(store, InMemoryBlobStore)


@pytest.mark.parametrize("environment", ("staging", "production"))
def test_blob_factory_refuses_in_memory_store_outside_local(environment: str) -> None:
    """Uploads would not survive a restart or a second replica."""
    with pytest.raises(RuntimeError, match="memory is not allowed"):
        build_blob_store(_settings(environment=environment))


def test_scanner_factory_returns_disabled_scanner_locally() -> None:
    assert isinstance(build_malware_scanner(_settings()), DisabledScanner)


@pytest.mark.parametrize("environment", ("staging", "production"))
def test_scanner_factory_refuses_disabled_scanner_outside_local(environment: str) -> None:
    """Unscanned uploads reaching the model is a configuration error, not a mode (020)."""
    with pytest.raises(RuntimeError, match="disabled is not allowed"):
        build_malware_scanner(_settings(environment=environment))


def test_scanner_factory_selects_clamav_when_configured() -> None:
    scanner = build_malware_scanner(_settings(scanner_backend="clamav", clamav_host="clamd"))
    assert not isinstance(scanner, DisabledScanner)
    assert hasattr(scanner, "scan")


def test_document_parser_supports_plain_text_without_optional_extras() -> None:
    """A lean install must still parse text/plain, csv and markdown."""
    parser = build_document_parser(_settings())
    assert parser.supports("text/plain")
    assert parser.supports("text/markdown")
    assert parser.supports("text/csv")


def test_image_ocr_defaults_to_auto() -> None:
    """Default auto enables progressive OCR when Tesseract and/or Vision are present."""
    config = _config()
    assert config.image_ocr_backend == "auto"
    assert config.image_ocr_model is None
    assert config.ocr_min_chars == 12
    assert config.image_ocr_max_bytes == 8 * 1024 * 1024


def test_image_ocr_backend_requires_a_model() -> None:
    """A gateway OCR backend without a model would silently reject every image."""
    with pytest.raises(ValueError, match="ATTACHMENTS_IMAGE_OCR_MODEL"):
        _config(image_ocr_backend="gateway")


def test_image_ocr_auto_allows_missing_model() -> None:
    """auto without a Vision alias is valid (Tesseract-only progressive)."""
    config = _config(image_ocr_backend="auto", image_ocr_model="")
    assert config.image_ocr_backend == "auto"
    assert config.image_ocr_model is None


def test_image_ocr_blank_model_is_normalised_to_absent() -> None:
    """An unanswered env placeholder is *absent*, not a stray empty string."""
    config = _config(image_ocr_backend="disabled", image_ocr_model="")
    assert config.image_ocr_model is None


def test_image_ocr_blank_model_still_trips_the_gateway_guard() -> None:
    """Enabling OCR with a placeholder left unanswered must fail at startup, not per upload."""
    with pytest.raises(ValueError, match="ATTACHMENTS_IMAGE_OCR_MODEL"):
        _config(image_ocr_backend="gateway", image_ocr_model="")


@pytest.mark.asyncio()
async def test_blob_store_port_is_satisfied_structurally() -> None:
    """The in-memory double must expose the whole port, not a convenient subset."""
    store: BlobStorePort = InMemoryBlobStore()
    assert await store.stat("missing") is None
    assert await store.exists("missing") is False


@pytest.mark.asyncio()
async def test_attachment_ports_are_not_built_when_disabled() -> None:
    assert await build_attachment_ports(_settings(), _unused_session_factory()) is None


@pytest.mark.asyncio()
async def test_attachment_ports_are_built_when_enabled_locally() -> None:
    ports = await build_attachment_ports(_settings(enabled=True), _unused_session_factory())
    assert ports is not None
    assert isinstance(ports.blob_store, InMemoryBlobStore)


@pytest.mark.asyncio()
async def test_attachment_ports_refuse_the_unsafe_defaults_outside_local() -> None:
    """Startup aborts: the defaults are an in-process store with no AV (020).

    Whichever guard trips first is fine — the point is that production cannot boot
    with the dev defaults. The per-backend guards are asserted individually above.
    """
    with pytest.raises(RuntimeError):
        await build_attachment_ports(
            _settings(environment="production", enabled=True),
            _unused_session_factory(),
        )


def _unused_session_factory() -> Any:
    """Placeholder: the port builders under test never open a session."""
    return cast("Any", None)
