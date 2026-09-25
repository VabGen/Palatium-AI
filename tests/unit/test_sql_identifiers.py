"""DDL identifier safety (020, P2): config values cannot inject into CREATE DATABASE/SCHEMA."""

from __future__ import annotations

import pytest

from palatium_ai.core.config.database import DatabaseConfig
from palatium_ai.core.security.identifiers import (
    UnsafeSqlIdentifierError,
    assert_safe_sql_identifier,
    quote_sql_identifier,
)


@pytest.mark.parametrize("name", ["palatium_dev", "palatium_ai", "d", "_internal", "mixed-Name_9"])
def test_safe_identifier_accepts_plain_names(name: str) -> None:
    assert assert_safe_sql_identifier(name) == name
    assert quote_sql_identifier(name) == f'"{name}"'


@pytest.mark.parametrize(
    "name",
    [
        'foo"; DROP DATABASE postgres; --',
        "foo; DROP DATABASE postgres",
        "foo bar",
        "1starts_with_digit",
        "-leading-hyphen",
        "",
        "a" * 64,
        'quote"inside',
    ],
)
def test_safe_identifier_rejects_injection_and_junk(name: str) -> None:
    with pytest.raises(UnsafeSqlIdentifierError):
        assert_safe_sql_identifier(name)


def _db_config(**overrides: str) -> DatabaseConfig:
    env = {"POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p", "POSTGRES_DB": "d", **overrides}
    return DatabaseConfig.model_validate(env)


def test_database_config_rejects_unsafe_db_name() -> None:
    with pytest.raises(ValueError):
        _db_config(POSTGRES_DB='foo"; DROP DATABASE postgres; --')


def test_database_config_rejects_unsafe_schema() -> None:
    with pytest.raises(ValueError):
        _db_config(POSTGRES_SCHEMA="bad schema")


def test_database_config_accepts_configured_examples() -> None:
    cfg = _db_config(POSTGRES_DB="palatium_prod", POSTGRES_SCHEMA="palatium_ai")
    assert cfg.db == "palatium_prod"
    assert cfg.db_schema == "palatium_ai"
