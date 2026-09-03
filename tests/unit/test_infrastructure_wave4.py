"""Wave 4 infrastructure unit tests (memory scope, hybrid merge, circuit helpers)."""

from __future__ import annotations

from palatium_ai.core.resilience.circuit import ConsecutiveFailureCircuit
from palatium_ai.infrastructure.memory.postgres_memory_port import (
    encode_namespace,
    merge_hybrid_scores,
    normalize_memory_type,
)
from palatium_ai.infrastructure.memory.user_scope import resolve_user_id


def test_resolve_user_id_from_namespace() -> None:
    assert resolve_user_id(("user", "alice")) == "alice"


def test_resolve_user_id_from_value() -> None:
    assert resolve_user_id(("org", "acme"), {"user_id": "bob"}) == "bob"


def test_resolve_user_id_org_fallback() -> None:
    assert resolve_user_id(("org", "acme")) == "org:acme"


def test_normalize_memory_type_maps_unknown_to_fact() -> None:
    assert normalize_memory_type({"kind": "entity"}) == "fact"
    assert normalize_memory_type({"kind": "preference"}) == "preference"


def test_merge_hybrid_scores_prefers_higher_blended_score() -> None:
    fts = [("a", 0.4, {"confidence": 0.5})]
    vector = [("a", 0.9, {"confidence": 0.5}), ("b", 0.2, {"confidence": 0.9})]
    merged = merge_hybrid_scores(fts, vector, limit=2)
    assert len(merged) == 2
    assert merged[0]["_score"] >= merged[1]["_score"]


def test_encode_namespace_escapes_slashes() -> None:
    assert encode_namespace(("chat", "thread", "t/1")) == "chat/thread/t_1"


def test_circuit_half_open_allows_single_probe() -> None:
    circuit = ConsecutiveFailureCircuit(failures_to_open=1, open_seconds=60.0)
    now = 1000.0
    circuit.record_failure(now)
    assert circuit.is_open(now + 1) is True
    assert circuit.allow_request(now + 61.0) is True
    assert circuit.is_open(now + 61.0) is True
    circuit.record_success()
    assert circuit.state == "closed"
