# src/palatium_ai/core/security/identifiers.py

"""SQL identifier safety (020): DDL names cannot be bound as query parameters.

PostgreSQL forbids parameter placeholders in DDL positions (``CREATE DATABASE``,
``CREATE SCHEMA``), so the only safe interpolation is a *validated* identifier.
Never build these statements from raw config/strings — validate then double-quote.
"""

from __future__ import annotations

import re

# ASCII letters / digits / underscore / hyphen, must start with a letter or underscore.
# Postgres NAMEDATALEN-1 = 63 bytes.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,62}$")


class UnsafeSqlIdentifierError(ValueError):
    """Raised when a config value is not a plain SQL identifier."""


def assert_safe_sql_identifier(name: str, *, kind: str = "identifier") -> str:
    """Return ``name`` when it is a plain quoted-safe identifier; raise otherwise."""
    candidate = str(name).strip()
    if not _IDENTIFIER_RE.match(candidate):
        raise UnsafeSqlIdentifierError(
            f"Unsafe SQL {kind} {name!r}: expected [A-Za-z_][A-Za-z0-9_-]* (max 63 chars)",
        )
    return candidate


def quote_sql_identifier(name: str, *, kind: str = "identifier") -> str:
    """Validate and double-quote an identifier for safe DDL interpolation."""
    return f'"{assert_safe_sql_identifier(name, kind=kind)}"'
