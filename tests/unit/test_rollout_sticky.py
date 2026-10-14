"""Sticky per-user Adaptive Grounding rollout (distribution branch, not PCT=100)."""

from __future__ import annotations

import pytest

from palatium_ai.core.observability.adaptive_grounding import is_adaptive_grounding_enabled


@pytest.fixture(autouse=True)
def _clear_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_rollout_sticky_pct_10_is_sticky_per_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """PCT=10 exercises hash8 % 100 — not the PCT>=100 short-circuit."""
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "true")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "10")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    uid = "user-ce9c4dcb-f202-4a9d-9079-c57e60a3d621"
    assert is_adaptive_grounding_enabled(uid) is is_adaptive_grounding_enabled(uid)

    enabled = sum(1 for i in range(10_000) if is_adaptive_grounding_enabled(f"user-{i}"))
    assert 800 <= enabled <= 1200


def test_master_off_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "false")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "100")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    assert is_adaptive_grounding_enabled("anyone") is False
