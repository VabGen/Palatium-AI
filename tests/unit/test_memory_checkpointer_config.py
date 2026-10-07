# tests/unit/test_memory_checkpointer_config.py

"""MemoryConfig dual TTL + deploy-aware Postgres checkpointer (Wave M1 / ADR 0003)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest

from palatium_ai.application.services.retention.windows import retention_windows_from_settings
from palatium_ai.core.config.app import AppConfig
from palatium_ai.core.config.memory import MemoryConfig
from palatium_ai.core.config.retention import RetentionConfig
from palatium_ai.core.config.settings import Settings
from palatium_ai.domain.policies.retention import RetentionPolicy

_NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
DeployEnv = Literal["staging", "production"]


def test_session_ttl_seconds_default() -> None:
    assert MemoryConfig().session_ttl_seconds == 1800


def test_postgres_checkpointer_off_in_development_when_unset() -> None:
    settings = Settings(
        app=AppConfig(environment="development"),
        memory=MemoryConfig(use_postgres_checkpointer=None),
    )
    assert settings.postgres_checkpointer_enabled is False


@pytest.mark.parametrize("environment", ("staging", "production"))
def test_postgres_checkpointer_on_in_deploy_when_unset(environment: DeployEnv) -> None:
    settings = Settings(
        app=AppConfig(environment=environment),
        memory=MemoryConfig(use_postgres_checkpointer=None),
    )
    assert settings.postgres_checkpointer_enabled is True


def test_postgres_checkpointer_explicit_false_wins_in_production() -> None:
    settings = Settings(
        app=AppConfig(environment="production"),
        memory=MemoryConfig(use_postgres_checkpointer=False),
    )
    assert settings.postgres_checkpointer_enabled is False


def test_retention_windows_wire_session_ttl_from_memory() -> None:
    settings = Settings(
        memory=MemoryConfig(session_ttl_seconds=900),
        retention=RetentionConfig(checkpoint_days=30),
    )
    windows = retention_windows_from_settings(settings)
    assert windows.session_ttl_seconds == 900
    assert windows.checkpoint_days == 30
    cutoff = RetentionPolicy.checkpoint_inactivity_cutoff(now=_NOW, windows=windows)
    assert cutoff == _NOW - timedelta(seconds=900)


def test_dual_ttl_resume_window_before_expire() -> None:
    """Within hot TTL the conversation is not reclaimable; past hot it is (cold later)."""
    windows = retention_windows_from_settings(
        Settings(
            memory=MemoryConfig(session_ttl_seconds=1800),
            retention=RetentionConfig(checkpoint_days=30),
        )
    )
    cutoff = RetentionPolicy.checkpoint_inactivity_cutoff(now=_NOW, windows=windows)
    last_activity_fresh = _NOW - timedelta(seconds=600)
    last_activity_stale = _NOW - timedelta(seconds=1801)
    assert last_activity_fresh >= cutoff  # still resumable until next job after idle
    assert last_activity_stale < cutoff  # expire / reclaim candidate
