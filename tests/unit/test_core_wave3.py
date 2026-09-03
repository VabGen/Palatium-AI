# tests/unit/test_core_wave3.py

"""Wave 3 core registries, circuit half-open, metrics, secret scan."""

from __future__ import annotations

from pathlib import Path

import pytest

from palatium_ai.core.context.tokens import count_tokens, record_context_tokens_used
from palatium_ai.core.exceptions import AuditChainIntegrityError
from palatium_ai.core.observability.audit import AuditChainLogger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.resilience.circuit import ConsecutiveFailureCircuit
from palatium_ai.core.security.secret_scanner import SecretScanError, scan_text
from palatium_ai.core.types.embeddings import (
    KNOWLEDGE_EMBEDDING_DIM,
    MEMORY_EMBEDDING_DIM,
    assert_vector_dim,
    embedding_model_for_schema,
)
from palatium_ai.core.types.model_registry import abstract_tier_for, context_limit_tokens


def test_embedding_registry_knowledge_memory_dims() -> None:
    assert embedding_model_for_schema("knowledge") == "text-embedding-3-small"
    assert embedding_model_for_schema("memory") == "qwen3-embedding-8b"
    assert KNOWLEDGE_EMBEDDING_DIM == 1536
    assert MEMORY_EMBEDDING_DIM == 4096
    assert_vector_dim(schema="memory", vector_len=4096)
    with pytest.raises(ValueError, match="Vector dim"):
        assert_vector_dim(schema="memory", vector_len=100)


def test_model_registry_context_limits() -> None:
    assert abstract_tier_for("nano") == "fast"
    assert abstract_tier_for("mid") == "standard"
    assert context_limit_tokens(model_tier="frontier") == 200_000
    assert context_limit_tokens(model_tier="small") == 32_000


def test_circuit_half_open_probe() -> None:
    circuit = ConsecutiveFailureCircuit(open_seconds=10.0)
    now = 100.0
    circuit.record_failure(now)
    circuit.record_failure(now)
    circuit.record_failure(now)
    assert circuit.state == "open"
    assert not circuit.allow_request(now)

    later = now + 11.0
    assert circuit.allow_request(later)
    assert circuit.state == "half_open"
    assert not circuit.allow_request(later)

    circuit.record_success()
    assert circuit.state == "closed"
    assert circuit.state_code() == 0


def test_context_token_metric() -> None:
    before = agent_metrics.context_tokens_count("researcher")
    record_context_tokens_used(agent_type="researcher", tokens=count_tokens("hello world"))
    assert agent_metrics.context_tokens_count("researcher") > before


def test_audit_blocks_secret_metadata(tmp_path: Path) -> None:
    path = tmp_path / "audit.log"
    logger = AuditChainLogger(file_path=path)
    with pytest.raises(AuditChainIntegrityError, match="Secret pattern"):
        logger.append(
            timestamp="2026-01-01T00:00:00Z",
            conversation_id="c1",
            event="permission_denied",
            metadata={"note": "leak sk-abcdefghijklmnopqrstuvwxyz123456"},
        )


def test_secret_scanner_blocks_sk_key() -> None:
    with pytest.raises(SecretScanError):
        scan_text("token sk-abcdefghijklmnopqrstuvwxyz123456")
