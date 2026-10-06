"""BlobStorePort adapters: in-memory behaviour and MinIO thread-dispatch (050)."""

from __future__ import annotations

import threading

from pathlib import Path
from urllib.parse import urlparse

import pytest

from palatium_ai.domain.ports.blob_store import BlobNotFoundError
from palatium_ai.infrastructure.blob.filesystem_adapter import FilesystemBlobStore
from palatium_ai.infrastructure.blob.in_memory_adapter import InMemoryBlobStore
from palatium_ai.infrastructure.blob.minio_adapter import MinIOAdapter, resolve_public_endpoint


def _minio_installed() -> bool:
    import importlib.util

    return importlib.util.find_spec("minio") is not None


def _files_under(root: Path) -> list[Path]:
    """Sync helper: ``rglob`` in an ``async def`` body is an ASYNC240 blocking call."""
    return [path for path in root.rglob("*") if path.is_file()]


def _part_files_under(root: Path) -> list[Path]:
    """Sync helper mirroring ``_files_under`` for the temp-file cleanup assertion."""
    return list(root.rglob("*.part"))


@pytest.mark.asyncio()
async def test_in_memory_store_round_trip() -> None:
    store = InMemoryBlobStore()
    await store.put_direct("attachments/abc", b"payload", content_type="text/plain")

    assert await store.exists("attachments/abc")
    assert await store.read_bytes("attachments/abc") == b"payload"
    stat = await store.stat("attachments/abc")
    assert stat is not None
    assert stat.size_bytes == 7
    assert stat.content_type == "text/plain"


@pytest.mark.asyncio()
async def test_in_memory_stat_returns_none_for_missing_key() -> None:
    store = InMemoryBlobStore()
    assert await store.stat("attachments/missing") is None
    assert not await store.exists("attachments/missing")


@pytest.mark.asyncio()
async def test_in_memory_read_missing_key_is_typed_error() -> None:
    """A missing object never surfaces as a bare KeyError past the port."""
    store = InMemoryBlobStore()
    with pytest.raises(BlobNotFoundError):
        await store.read_bytes("attachments/missing")


@pytest.mark.asyncio()
async def test_in_memory_delete_is_idempotent() -> None:
    store = InMemoryBlobStore()
    await store.put_direct("attachments/abc", b"x", content_type="text/plain")
    await store.delete("attachments/abc")
    await store.delete("attachments/abc")
    assert not await store.exists("attachments/abc")


@pytest.mark.asyncio()
async def test_in_memory_presigned_urls_are_time_boxed_and_distinguishable() -> None:
    store = InMemoryBlobStore(bucket="bucket")
    put = await store.presigned_put_url("attachments/abc", content_type="text/plain", expires_seconds=900)
    get = await store.presigned_get_url("attachments/abc", expires_seconds=900)
    assert "expires=900" in put
    assert "expires=900" in get


def test_minio_not_found_classification() -> None:
    """S3 NoSuchKey variants map to None instead of leaking the driver error."""

    class _S3Error(Exception):
        code = "NoSuchKey"

    assert MinIOAdapter._is_not_found(_S3Error())
    assert MinIOAdapter._is_not_found(Exception("The specified key does not exist."))
    assert not MinIOAdapter._is_not_found(Exception("Access Denied"))


def test_minio_missing_package_raises_actionable_error() -> None:
    """The optional extra must fail with a provisioning hint, not an ImportError."""
    if _minio_installed():
        pytest.skip("minio installed — the missing-package path is not reachable")
    with pytest.raises(RuntimeError, match="poetry install --with attachments"):
        MinIOAdapter(
            endpoint="localhost:9000",
            access_key="k",
            secret_key="s",
            bucket="b",
        )


@pytest.mark.asyncio()
async def test_minio_dispatches_blocking_sdk_calls_to_a_worker_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression for 050: a blocking SDK call on the event loop stalls the graph."""
    if not _minio_installed():
        pytest.skip("minio not installed — install with `poetry install --with attachments`")

    import minio

    observed: dict[str, int] = {}

    class _FakeStat:
        size = 3
        content_type = "text/plain"

    class _FakeClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def stat_object(self, _bucket: str, _key: str) -> _FakeStat:
            observed["thread"] = threading.get_ident()
            return _FakeStat()

        def presigned_put_object(self, _bucket: str, _key: str, *, expires: object) -> str:
            observed["thread"] = threading.get_ident()
            return "https://example.invalid/put"

    monkeypatch.setattr(minio, "Minio", _FakeClient)
    adapter = MinIOAdapter(endpoint="localhost:9000", access_key="k", secret_key="s", bucket="b")
    stat = await adapter.stat("attachments/abc")
    await adapter.presigned_put_url("attachments/abc", content_type="text/plain", expires_seconds=60)

    assert stat is not None
    assert stat.size_bytes == 3
    assert observed["thread"] != threading.get_ident()


@pytest.mark.asyncio()
async def test_filesystem_store_round_trip(tmp_path: Path) -> None:
    store = FilesystemBlobStore(root=tmp_path, bucket="bucket")
    await store.write_bytes("attachments/abc", b"payload", content_type="text/plain")

    stat = await store.stat("attachments/abc")
    assert stat is not None
    assert stat.size_bytes == 7
    assert stat.content_type == "text/plain"
    assert await store.read_bytes("attachments/abc") == b"payload"
    assert await store.exists("attachments/abc")


@pytest.mark.asyncio()
async def test_filesystem_store_is_visible_to_a_second_instance(tmp_path: Path) -> None:
    """The reason this backend exists: the documented 2-worker setup shares objects."""
    await FilesystemBlobStore(root=tmp_path).write_bytes("attachments/abc", b"payload", content_type="text/plain")

    reopened = FilesystemBlobStore(root=tmp_path)

    assert await reopened.read_bytes("attachments/abc") == b"payload"


@pytest.mark.asyncio()
async def test_filesystem_store_missing_object_is_typed_and_absent(tmp_path: Path) -> None:
    store = FilesystemBlobStore(root=tmp_path)
    assert await store.stat("attachments/missing") is None
    assert await store.exists("attachments/missing") is False
    with pytest.raises(BlobNotFoundError):
        await store.read_bytes("attachments/missing")


@pytest.mark.asyncio()
async def test_filesystem_store_delete_is_idempotent_and_leaves_no_metadata(tmp_path: Path) -> None:
    store = FilesystemBlobStore(root=tmp_path)
    await store.write_bytes("attachments/abc", b"x", content_type="text/plain")

    await store.delete("attachments/abc")
    await store.delete("attachments/abc")

    assert not await store.exists("attachments/abc")
    # The content-type sidecar must go with the object, or the next upload of the
    # same key would inherit a stale media type.
    assert _files_under(tmp_path) == []


@pytest.mark.asyncio()
async def test_filesystem_store_writes_atomically(tmp_path: Path) -> None:
    """No in-flight temp file may survive a completed write."""
    store = FilesystemBlobStore(root=tmp_path)
    await store.write_bytes("attachments/abc", b"payload", content_type="text/plain")

    assert _part_files_under(tmp_path) == []


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "key",
    ("../escape.txt", "attachments/../../escape.txt", "/absolute-escape.txt"),
)
async def test_filesystem_store_refuses_keys_that_escape_the_root(tmp_path: Path, key: str) -> None:
    """Traversal must fail loudly rather than write outside the configured root (020)."""
    root = tmp_path / "root"
    root.mkdir()
    store = FilesystemBlobStore(root=root)

    with pytest.raises(ValueError, match="escapes the storage root"):
        await store.write_bytes(key, b"payload", content_type="text/plain")

    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.asyncio()
async def test_filesystem_presigned_urls_are_placeholders_not_http(tmp_path: Path) -> None:
    """The client picks the transport by scheme: non-http means 'send the bytes via the API'."""
    store = FilesystemBlobStore(root=tmp_path, bucket="bucket")

    put = await store.presigned_put_url("attachments/abc", content_type="text/plain", expires_seconds=900)
    get = await store.presigned_get_url("attachments/abc", expires_seconds=900)

    assert put.startswith("filesystem://")
    assert "expires=900" in put
    assert get.startswith("filesystem://")
    assert not put.startswith("http")


# ── Presign host vs connection host (020) ─────────────────────────────────────────
# SigV4 signs the Host header, so a presigned URL is only valid for the host it was
# signed against. Inside a compose network the API connects to `minio:9000` while the
# browser resolves `127.0.0.1:9000`; signing against the in-cluster name would hand the
# browser a URL it cannot reach, and the row would sit in `pending` forever.


@pytest.mark.parametrize(
    "value,fallback,expected",
    (
        (None, False, None),
        ("", False, None),
        ("   ", True, None),
        ("127.0.0.1:9000", True, ("127.0.0.1:9000", True)),
        # A service named `minio` must not be parsed as the scheme `minio`.
        ("minio:9000", False, ("minio:9000", False)),
        ("http://127.0.0.1:9000", True, ("127.0.0.1:9000", False)),
        ("https://s3.corp.example", False, ("s3.corp.example", True)),
        ("https://s3.corp.example:9443/", False, ("s3.corp.example:9443", True)),
    ),
)
def test_resolve_public_endpoint_normalises_accepted_forms(
    value: str | None,
    fallback: bool,
    expected: tuple[str, bool] | None,
) -> None:
    assert resolve_public_endpoint(value, fallback_secure=fallback) == expected


@pytest.mark.parametrize("value", ("ftp://s3.corp.example", "http://", "s3.corp.example/path"))
def test_resolve_public_endpoint_rejects_malformed_values(value: str) -> None:
    """A typo must abort wiring, not silently presign against the wrong host (020)."""
    with pytest.raises(ValueError, match="ATTACHMENTS_MINIO_PUBLIC_ENDPOINT"):
        resolve_public_endpoint(value, fallback_secure=False)


@pytest.mark.asyncio()
async def test_minio_presigns_against_the_public_endpoint() -> None:
    """Regression: the browser must receive the public host, not the in-cluster one."""
    if not _minio_installed():
        pytest.skip("minio not installed — install with `poetry install --with attachments`")

    adapter = MinIOAdapter(
        endpoint="minio:9000",
        access_key="k",
        secret_key="s",
        bucket="palatium-attachments",
        public_endpoint="http://127.0.0.1:9000",
    )

    put = await adapter.presigned_put_url("attachments/abc", content_type="text/plain", expires_seconds=900)
    get = await adapter.presigned_get_url("attachments/abc", expires_seconds=900)

    assert urlparse(put).netloc == "127.0.0.1:9000"
    assert urlparse(get).netloc == "127.0.0.1:9000"
    assert adapter.public_endpoint == "127.0.0.1:9000"
    # The signature covers the public host, so swapping the netloc back to the
    # in-cluster name would invalidate the URL — which is why this is a config knob.
    assert "X-Amz-Signature" in put


@pytest.mark.asyncio()
async def test_minio_presign_falls_back_to_the_connection_endpoint() -> None:
    """Unset means 'one address for both', so the existing single-host setups keep working."""
    if not _minio_installed():
        pytest.skip("minio not installed — install with `poetry install --with attachments`")

    adapter = MinIOAdapter(
        endpoint="127.0.0.1:9000",
        access_key="k",
        secret_key="s",
        bucket="palatium-attachments",
    )

    put = await adapter.presigned_put_url("attachments/abc", content_type="text/plain", expires_seconds=900)

    assert urlparse(put).netloc == "127.0.0.1:9000"
    assert adapter.public_endpoint is None


@pytest.mark.asyncio()
async def test_minio_public_endpoint_scheme_decides_tls_for_the_browser() -> None:
    """An https public endpoint must yield an https URL even when the cluster link is plain."""
    if not _minio_installed():
        pytest.skip("minio not installed — install with `poetry install --with attachments`")

    adapter = MinIOAdapter(
        endpoint="minio:9000",
        access_key="k",
        secret_key="s",
        bucket="palatium-attachments",
        secure=False,
        public_endpoint="https://s3.corp.example",
    )

    put = await adapter.presigned_put_url("attachments/abc", content_type="text/plain", expires_seconds=900)

    assert urlparse(put).scheme == "https"
    assert urlparse(put).netloc == "s3.corp.example"


class _FakeS3Error(Exception):
    """Stand-in for ``minio.error.S3Error``, whose contract is a ``code`` attribute."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _fake_minio_client_raising_on_make_bucket(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    """Install a client that always reports "no bucket", then fails the create."""
    if not _minio_installed():
        pytest.skip("minio not installed — install with `poetry install --with attachments`")

    import minio

    class _FakeClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def bucket_exists(self, _bucket: str) -> bool:
            # False on purpose: this is the check-then-act window the race lives in.
            return False

        def make_bucket(self, _bucket: str) -> None:
            raise error

    monkeypatch.setattr(minio, "Minio", _FakeClient)


@pytest.mark.asyncio()
@pytest.mark.parametrize("code", ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"))
async def test_minio_ensure_bucket_tolerates_the_startup_create_race(
    monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    """Regression: concurrent API workers both create the bucket at startup.

    Observed against a live store: the loser received ``BucketAlreadyOwnedByYou``, the
    exception escaped ``ensure_bucket()``, and the process exited with "Application
    startup failed" — a crash-loop for a race whose outcome is exactly what we wanted.
    """
    _fake_minio_client_raising_on_make_bucket(monkeypatch, _FakeS3Error(code))
    adapter = MinIOAdapter(endpoint="localhost:9000", access_key="k", secret_key="s", bucket="b")

    assert await adapter.ensure_bucket() is True


@pytest.mark.asyncio()
async def test_minio_ensure_bucket_still_fails_closed_on_other_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the benign race is tolerated: permissions/network errors must still surface."""
    _fake_minio_client_raising_on_make_bucket(monkeypatch, _FakeS3Error("AccessDenied"))
    adapter = MinIOAdapter(endpoint="localhost:9000", access_key="k", secret_key="s", bucket="b")

    with pytest.raises(_FakeS3Error, match="AccessDenied"):
        await adapter.ensure_bucket()
