"""Postgres integration for platform search_memory (opt-in)."""

from __future__ import annotations

import json

import pytest

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler
from palatium_ai.infrastructure.memory.postgres_memory_port import PostgresMemoryPort


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_search_memory_after_save(requires_database: str) -> None:
    engine = create_async_engine(requires_database)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    memory_port = PostgresMemoryPort(session_factory)
    handler = PlatformToolHandler(memory_port=memory_port)

    save = await handler.call_tool(
        "save_memory",
        {
            "user_id": "integration-user",
            "namespace_kind": "user",
            "scope_id": "integration-user",
            "entry_key": "integration-pref-lang",
            "value_json": json.dumps({"text": "Integration user prefers Russian UI labels.", "confidence": 0.9}),
            "memory_type": "preference",
        },
    )
    assert save.is_error is False

    search = await handler.call_tool(
        "search_memory",
        {
            "user_id": "integration-user",
            "query": "Russian UI",
            "limit": "5",
        },
    )
    assert search.is_error is False
    payload = json.loads(search.content[0]["text"])
    assert payload["hit_count"] >= 1
    await engine.dispose()
