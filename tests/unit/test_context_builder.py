"""Wave 8: ContextBuilder JIT assembly (065)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from palatium_ai.application.services.context_builder import ContextBuilder
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow


@pytest.mark.asyncio
async def test_build_returns_empty_for_no_keys() -> None:
    builder = ContextBuilder()
    assert await builder.build([], thread_id="t1") == {}


@pytest.mark.asyncio
async def test_build_loads_history_from_dialog_store() -> None:
    dialog_store = AsyncMock()
    dialog_store.list_recent_turns.return_value = DialogTurnWindow(
        thread_id="t1",
        turns=(
            DialogTurn(thread_id="t1", role="user", content="hello"),
            DialogTurn(thread_id="t1", role="assistant", content="hi there"),
        ),
    )
    builder = ContextBuilder(dialog_store=dialog_store)
    context = await builder.build(["history"], thread_id="t1")
    assert context["history"] == "user: hello\nassistant: hi there"
    dialog_store.list_recent_turns.assert_awaited_once_with(thread_id="t1", limit=12)


@pytest.mark.asyncio
async def test_build_raises_for_unknown_key() -> None:
    builder = ContextBuilder()
    with pytest.raises(KeyError, match="Unknown or unavailable context key"):
        await builder.build(["goal"], thread_id="t1")


@pytest.mark.asyncio
async def test_build_loads_long_term_memory_when_user_present() -> None:
    memory_port = AsyncMock()
    memory_port.search.return_value = [{"text": "prefers concise answers"}]
    builder = ContextBuilder(memory_port=memory_port)
    context = await builder.build(
        ["long_term_memory"],
        thread_id="t1",
        user_id="alice",
        instruction="summarize",
    )
    assert context["long_term_memory"] == "prefers concise answers"
    memory_port.search.assert_awaited_once()
