"""Unit tests for Neo4j MemoryFact runtime schema bootstrap (Phase 4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from palatium_ai.infrastructure.memory.neo4j_schema import ensure_memory_schema


@pytest.mark.asyncio()
async def test_ensure_memory_schema_idempotent() -> None:
    driver = AsyncMock()
    # First call: full batch; second: drained; then two index statements + constraint.
    driver.execute_query.side_effect = [
        MagicMock(records=[{"n": 5000}]),
        MagicMock(records=[{"n": 0}]),
        MagicMock(records=[]),
        MagicMock(records=[]),
        MagicMock(records=[]),
    ]

    result = await ensure_memory_schema(driver)

    assert result == 5000
    assert driver.execute_query.call_count == 5
    statements = [str(call.args[0]) for call in driver.execute_query.call_args_list]
    assert any("CREATE CONSTRAINT memory_fact_node_id" in statement for statement in statements)
    assert any("REQUIRE f.node_id IS UNIQUE" in statement for statement in statements)


@pytest.mark.asyncio()
async def test_ensure_memory_schema_single_partial_batch() -> None:
    driver = AsyncMock()
    driver.execute_query.side_effect = [
        MagicMock(records=[{"n": 42}]),
        MagicMock(records=[]),
        MagicMock(records=[]),
        MagicMock(records=[]),
    ]

    result = await ensure_memory_schema(driver)

    assert result == 42
    assert driver.execute_query.call_count == 4


@pytest.mark.asyncio()
async def test_constraint_failure_is_reported_but_does_not_abort_startup() -> None:
    """Legacy duplicates block the constraint; startup must still come up, loudly."""
    driver = AsyncMock()

    async def _execute(statement: str, **_kwargs: object) -> MagicMock:
        if "CREATE CONSTRAINT" in statement:
            raise RuntimeError("ConstraintCreationFailed: duplicate node_id")
        return MagicMock(records=[])

    driver.execute_query.side_effect = _execute

    result = await ensure_memory_schema(driver)

    assert result == 0
    assert driver.execute_query.call_count == 4
