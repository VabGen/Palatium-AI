# tests/unit/test_memory_corroboration.py

"""CMD1.6 batch trust upgrades."""

from __future__ import annotations

import pytest

from palatium_ai.application.services.memory_corroboration import MemoryCorroborationService
from palatium_ai.domain.memory.corroboration import CorroborationEntry, propose_trust_upgrades
from palatium_ai.domain.memory.namespaces import thread_namespace
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort


def test_propose_upgrade_from_verified_overlap() -> None:
    ns = thread_namespace("t-corr")
    entries = [
        CorroborationEntry(
            namespace=ns,
            entry_key="v1",
            text="User prefers duck for dinner",
            trust="verified",
            origin="user_hitl",
        ),
        CorroborationEntry(
            namespace=ns,
            entry_key="i1",
            text="User prefers duck for dinner tonight",
            trust="inferred",
            origin="extract",
            source_task_id="extract-a",
        ),
    ]
    upgrades = propose_trust_upgrades(entries)
    assert len(upgrades) == 1
    assert upgrades[0].entry_key == "i1"
    assert upgrades[0].reason == "verified_overlap"


def test_propose_upgrade_from_peer_extract() -> None:
    ns = thread_namespace("t-peer")
    entries = [
        CorroborationEntry(
            namespace=ns,
            entry_key="a",
            text="Database port is 5432",
            trust="inferred",
            origin="extract",
            source_task_id="job-1",
        ),
        CorroborationEntry(
            namespace=ns,
            entry_key="b",
            text="Database port is 5432",
            trust="inferred",
            origin="extract",
            source_task_id="job-2",
        ),
    ]
    upgrades = propose_trust_upgrades(entries)
    keys = {u.entry_key for u in upgrades}
    assert keys == {"a", "b"}
    assert all(u.reason == "peer_extract" for u in upgrades)


def test_same_task_id_does_not_corroborate() -> None:
    ns = thread_namespace("t-same")
    entries = [
        CorroborationEntry(
            namespace=ns,
            entry_key="a",
            text="likes tea",
            trust="inferred",
            origin="extract",
            source_task_id="job-1",
        ),
        CorroborationEntry(
            namespace=ns,
            entry_key="b",
            text="likes tea",
            trust="inferred",
            origin="extract",
            source_task_id="job-1",
        ),
    ]
    assert propose_trust_upgrades(entries) == ()


@pytest.mark.asyncio()
async def test_corroboration_service_persists_trust() -> None:
    port = InMemoryMemoryPort()
    ns = thread_namespace("t-svc")
    await port.put(
        namespace=ns,
        key="hitl",
        value={
            "text": "User email is a@example.com",
            "kind": "fact",
            "confidence": 0.95,
            "origin": "user_hitl",
            "trust": "verified",
        },
    )
    await port.put(
        namespace=ns,
        key="ext",
        value={
            "text": "User email is a@example.com",
            "kind": "fact",
            "confidence": 0.9,
            "origin": "extract",
            "trust": "inferred",
            "source_task_id": "extract-9",
        },
    )
    service = MemoryCorroborationService(port)
    entries = MemoryCorroborationService.entries_from_items(
        [
            (ns, "hitl", (await port.get(namespace=ns, key="hitl")) or {}),
            (ns, "ext", (await port.get(namespace=ns, key="ext")) or {}),
        ]
    )
    updated = await service.run_for_entries(entries)
    assert updated == 1
    stored = await port.get(namespace=ns, key="ext")
    assert stored is not None
    assert stored["trust"] == "verified"
