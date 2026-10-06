# tests/unit/test_memory_write_service.py

"""Gated MemoryWriteService unit tests (Wave M4)."""

from __future__ import annotations

import pytest

from palatium_ai.application.services.memory_write_service import MemoryWriteService
from palatium_ai.domain.memory.namespaces import thread_namespace
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort


@pytest.mark.asyncio()
async def test_put_system_persists_after_gates() -> None:
    port = InMemoryMemoryPort()
    writer = MemoryWriteService(port)
    ok = await writer.put_system(
        namespace_kind="thread",
        scope_id="t1",
        entry_key="compact_preserve:goal",
        text="Ship gated compact",
        source="context_compact",
        thread_id="t1",
        user_id="u1",
    )
    assert ok is True
    stored = await port.get(namespace=thread_namespace("t1"), key="compact_preserve:goal")
    assert stored is not None
    assert "gated compact" in str(stored.get("text", "")).lower()
    assert stored.get("contains_pii") is False
    assert stored.get("source") == "context_compact"


@pytest.mark.asyncio()
async def test_put_system_rejects_secret_shaped_text() -> None:
    port = InMemoryMemoryPort()
    writer = MemoryWriteService(port)
    ok = await writer.put_system(
        namespace_kind="thread",
        scope_id="t-secret",
        entry_key="compact_preserve:goal",
        text="goal uses sk-abcdefghijklmnopqrstuv password=hunter2",
        source="context_compact",
        thread_id="t-secret",
    )
    assert ok is False
    assert await port.get(namespace=thread_namespace("t-secret"), key="compact_preserve:goal") is None


@pytest.mark.asyncio()
async def test_put_system_empty_text_noop() -> None:
    port = InMemoryMemoryPort()
    writer = MemoryWriteService(port)
    assert (
        await writer.put_system(
            namespace_kind="thread",
            scope_id="t0",
            entry_key="k",
            text="   ",
            source="context_compact",
            thread_id="t0",
        )
        is False
    )
