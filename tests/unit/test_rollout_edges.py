"""Two-key Adaptive Grounding flag edge semantics."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from palatium_ai.core.observability.adaptive_grounding import (
    is_adaptive_grounding_enabled,
    warn_if_enabled_but_zero_rollout,
)


@pytest.fixture(autouse=True)
def _clear_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_enabled_true_pct_zero_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "true")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "0")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    assert is_adaptive_grounding_enabled("any") is False


def test_enabled_false_pct_100_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "false")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "100")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    assert is_adaptive_grounding_enabled("any") is False


def test_two_key_requires_both(monkeypatch: pytest.MonkeyPatch) -> None:
    from palatium_ai.core.config import get_settings

    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "true")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "0")
    get_settings.cache_clear()
    assert is_adaptive_grounding_enabled("any") is False

    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "false")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "100")
    get_settings.cache_clear()
    assert is_adaptive_grounding_enabled("any") is False

    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "true")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "100")
    get_settings.cache_clear()
    assert is_adaptive_grounding_enabled("any") is True


def test_warning_on_enabled_true_pct_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "true")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "0")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    mock_log = MagicMock()
    with patch(
        "palatium_ai.core.observability.adaptive_grounding.logger",
        mock_log,
    ):
        warn_if_enabled_but_zero_rollout(get_settings())
    mock_log.warning.assert_called_once()
    assert mock_log.warning.call_args.args[0] == (
        "adaptive_grounding.enabled_but_zero_rollout"
    )


def test_no_warning_when_pct_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "true")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "10")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    mock_log = MagicMock()
    with patch(
        "palatium_ai.core.observability.adaptive_grounding.logger",
        mock_log,
    ):
        warn_if_enabled_but_zero_rollout(get_settings())
    mock_log.warning.assert_not_called()
