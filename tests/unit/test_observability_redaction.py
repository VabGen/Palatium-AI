"""Observability boundary redaction (PII / tokens)."""

from __future__ import annotations

import pytest

from palatium_ai.core.observability.redaction import bucket_len, hash8, redact


@pytest.mark.parametrize(
    "raw,expected",
    (
        ("пароль sk-abc123456789012345", "пароль <token>"),
        ("пиши ivan@example.com", "пиши <email>"),
        ("файл /Users/gena/x.txt", "файл <path>"),
        ("+375291234567", "<phone>"),
        ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghij", "<jwt>"),
        ("УНП 123456789", "УНП <unp>"),
        ("BY12ABCD1234567890", "<iban_by>"),
    ),
)
def test_redact(raw: str, expected: str) -> None:
    assert redact(raw) == expected


def test_redact_idempotent() -> None:
    once = redact("sk-abc123456789012345")
    assert redact(once) == once


def test_redact_truncates() -> None:
    long = "a" * 1000
    assert len(redact(long) or "") == 256


def test_hash8_stable() -> None:
    assert hash8("same") == hash8("same")
    assert hash8("same") != hash8("other")
    assert len(hash8("x")) == 8


def test_bucket_len() -> None:
    assert bucket_len(None) == "empty"
    assert bucket_len("short") == "0-50"
    assert bucket_len("x" * 80) == "50-200"
