"""Audit chain integrity: refuse silent genesis on corrupt tail."""

from __future__ import annotations

from pathlib import Path

import pytest

from palatium_ai.core.exceptions import AuditChainIntegrityError
from palatium_ai.core.observability.audit import AuditChainLogger


def test_append_chains_from_genesis(tmp_path: Path) -> None:
    path = tmp_path / "audit.log"
    logger = AuditChainLogger(file_path=path)
    first = logger.append(
        timestamp="t1",
        conversation_id="c1",
        event="e1",
        metadata={"k": "v"},
    )
    assert first.previous_hash == "genesis"
    second = logger.append(
        timestamp="t2",
        conversation_id="c1",
        event="e2",
    )
    assert second.previous_hash == first.current_hash


def test_corrupt_tail_raises(tmp_path: Path) -> None:
    path = tmp_path / "audit.log"
    path.write_text('{"current_hash":"abc"}\nNOT-JSON\n', encoding="utf-8")
    logger = AuditChainLogger(file_path=path)
    with pytest.raises(AuditChainIntegrityError, match="Corrupt audit chain JSON"):
        logger.append(timestamp="t", conversation_id="c", event="e")


def test_missing_current_hash_raises(tmp_path: Path) -> None:
    path = tmp_path / "audit.log"
    path.write_text('{"event":"x"}\n', encoding="utf-8")
    logger = AuditChainLogger(file_path=path)
    with pytest.raises(AuditChainIntegrityError, match="Missing current_hash"):
        logger.append(timestamp="t", conversation_id="c", event="e")


def test_hmac_mac_when_secret_set(tmp_path: Path) -> None:
    path = tmp_path / "audit.log"
    logger = AuditChainLogger(file_path=path, hmac_secret="unit-test-audit-hmac")  # noqa: S106
    record = logger.append(timestamp="t", conversation_id="c", event="e")
    assert record.integrity_mac is not None
    assert len(record.integrity_mac) == 64
