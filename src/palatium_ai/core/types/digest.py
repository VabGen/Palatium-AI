"""Content digest constants and helpers (010 — single source for hex length)."""

from __future__ import annotations

import hashlib
import secrets

# SHA-256 hex digest length (never magic ``64`` at call sites).
SHA256_HEX_LENGTH = 64

__all__ = [
    "SHA256_HEX_LENGTH",
    "assert_sha256_hex_match",
    "sha256_hex",
]


def sha256_hex(data: bytes) -> str:
    """Lowercase hex SHA-256 of raw bytes (attachment blob integrity)."""
    return hashlib.sha256(data).hexdigest()


def assert_sha256_hex_match(*, expected: str, actual_hex: str) -> bool:
    """Constant-time compare of two lowercase hex digests; True when equal."""
    return secrets.compare_digest(expected.lower(), actual_hex.lower())
