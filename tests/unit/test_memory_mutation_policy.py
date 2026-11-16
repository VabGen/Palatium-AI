"""MemoryMutationPolicy — deterministic key + existing-target resolution (055)."""

from __future__ import annotations

from palatium_ai.domain.policies.memory_mutation import MEMORY_KEY_PREFIX, MemoryMutationPolicy


def test_coerce_text_normalizes_but_does_not_rewrite() -> None:
    assert MemoryMutationPolicy.coerce_text("  «порт   базы 5433»  ") == "порт базы 5433"
    assert MemoryMutationPolicy.coerce_text(None) == ""
    assert MemoryMutationPolicy.coerce_text(42) == ""


def test_coerce_key_prefers_model_slug() -> None:
    assert MemoryMutationPolicy.coerce_key("DB Port", text="порт 5433") == "db-port"


def test_coerce_key_falls_back_to_statement_digest() -> None:
    key = MemoryMutationPolicy.coerce_key("", text="порт базы 5433")
    assert key.startswith(MEMORY_KEY_PREFIX)
    # Stable across turns: the same fact cannot fork into two entries.
    assert key == MemoryMutationPolicy.coerce_key(None, text="порт базы 5433")


def test_best_existing_match_uses_overlap_coefficient() -> None:
    hits = [
        {"_entry_key": "db_port", "text": "порт базы данных 5432", "_score": 0.9},
        {"_entry_key": "coffee", "text": "люблю кофе", "_score": 0.2},
    ]
    match = MemoryMutationPolicy.best_existing_match(hits, text="порт базы 5433")
    assert match is not None
    assert match["_entry_key"] == "db_port"


def test_best_existing_match_rejects_weak_overlap() -> None:
    hits = [{"_entry_key": "coffee", "text": "люблю кофе", "_score": 0.9}]
    assert MemoryMutationPolicy.best_existing_match(hits, text="люблю чай") is None


def test_best_existing_match_requires_addressable_key() -> None:
    hits = [{"text": "порт базы данных 5432", "_score": 1.0}]
    assert MemoryMutationPolicy.best_existing_match(hits, text="порт базы") is None
