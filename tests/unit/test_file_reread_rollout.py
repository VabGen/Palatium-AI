"""Thread file re-read rollout gate — sticky cohorts and the one-variable rollback (055)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from palatium_ai.core.config import get_settings
from palatium_ai.core.observability.file_reread_rollout import (
    is_file_reread_enabled,
    resolve_file_reread,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _clean_settings_cache() -> Iterator[None]:
    """monkeypatch reverts env after each test; a stale cached Settings would poison the next."""
    yield
    get_settings.cache_clear()


def test_pct_zero_is_off_for_every_caller() -> None:
    assert resolve_file_reread(0, "any") is False
    assert resolve_file_reread(-1, "any") is False


def test_pct_100_is_on_for_every_caller_including_anonymous() -> None:
    assert resolve_file_reread(100, None) is True
    assert resolve_file_reread(100, "") is True
    assert resolve_file_reread(150, "any") is True


def test_canary_bucket_is_sticky_per_user() -> None:
    """PCT=10 must exercise the hash8 branch, not the PCT>=100 short-circuit."""
    uid = "user-ce9c4dcb-f202-4a9d-9079-c57e60a3d621"
    assert resolve_file_reread(10, uid) is resolve_file_reread(10, uid)

    enabled = sum(1 for index in range(10_000) if resolve_file_reread(10, f"user-{index}"))
    assert 800 <= enabled <= 1200


def test_missing_user_falls_back_to_a_stable_anonymous_bucket() -> None:
    assert resolve_file_reread(50, None) is resolve_file_reread(50, "")


def test_settings_gate_reads_the_attachments_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTACHMENTS_FILE_REREAD_PCT", "100")
    get_settings.cache_clear()
    assert is_file_reread_enabled("anyone") is True

    monkeypatch.setenv("ATTACHMENTS_FILE_REREAD_PCT", "0")
    get_settings.cache_clear()
    assert is_file_reread_enabled("anyone") is False


def test_dark_by_default_without_configuration() -> None:
    """Absent configuration must not enable a new tool-dispatch path (020 fail-closed).

    Asserts the declared default, not the resolved value: ``tests/conftest.py`` seeds
    ``os.environ`` from ``env/.env.example``, so a resolved Settings object would
    assert on the example file instead of on the code default.
    """
    from palatium_ai.core.config.attachments import AttachmentConfig

    assert AttachmentConfig.model_fields["file_reread_pct"].default == 0
