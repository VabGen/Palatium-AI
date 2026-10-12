"""Unit tests for Neo4j MemoryFact runtime schema bootstrap (Phase 4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from palatium_ai.infrastructure.memory.neo4j_schema import ensure_memory_schema


@pytest.mark.asyncio()
async def test_ensure_memory_schema_idempotent() -> None:
    driver = AsyncMock()
    # First call: full batch; second: drained; then two index statements.
    driver.execute_query.side_effect = [
        MagicMock(records=[{"n": 5000}]),
        MagicMock(records=[{"n": 0}]),
        MagicMock(records=[]),
        MagicMock(records=[]),
    ]

    result = await ensure_memory_schema(driver)

    assert result == 5000
    assert driver.execute_query.call_count == 4


@pytest.mark.asyncio()
async def test_ensure_memory_schema_single_partial_batch() -> None:
    driver = AsyncMock()
    driver.execute_query.side_effect = [
        MagicMock(records=[{"n": 42}]),
        MagicMock(records=[]),
        MagicMock(records=[]),
    ]

    result = await ensure_memory_schema(driver)

    assert result == 42
    assert driver.execute_query.call_count == 3
