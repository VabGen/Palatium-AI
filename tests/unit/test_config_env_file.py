"""ENV_FILE / empty-process-env normalisation for settings load (alembic, API)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from palatium_ai.core.config.base import resolve_env_file

if TYPE_CHECKING:
    import pytest
from palatium_ai.core.config.database import DatabaseConfig


def test_resolve_env_file_treats_blank_as_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENV_FILE", raising=False)
    assert resolve_env_file() == "env/.env"

    monkeypatch.setenv("ENV_FILE", "")
    assert resolve_env_file() == "env/.env"

    monkeypatch.setenv("ENV_FILE", "   ")
    assert resolve_env_file() == "env/.env"

    monkeypatch.setenv("ENV_FILE", "env/.env.dev")
    assert resolve_env_file() == "env/.env.dev"


def test_database_config_ignores_empty_postgres_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Blank ``POSTGRES_HOST=`` / ``PORT=`` in the shell must not wipe the env file.

    Reproduces the alembic ``upgrade head`` failure after compose/make left empty
    client vars in the operator shell while ``ENV_FILE`` was also blank.
    """
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            (
                'POSTGRES_HOST="localhost"',
                "POSTGRES_PORT=5432",
                'POSTGRES_USER="postgres"',
                'POSTGRES_PASSWORD="secret"',
                'POSTGRES_DB="postgres"',
                'POSTGRES_SCHEMA="palatium_ai"',
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("POSTGRES_HOST", "")
    monkeypatch.setenv("POSTGRES_PORT", "")
    for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_SCHEMA"):
        monkeypatch.delenv(key, raising=False)

    cfg = DatabaseConfig(_env_file=str(env_path))  # type: ignore[call-arg]

    assert cfg.host == "localhost"
    assert cfg.port == 5432
    assert cfg.user == "postgres"
    assert cfg.db == "postgres"
