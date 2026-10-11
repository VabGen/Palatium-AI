"""Turn correlation (session_id / turn_id / trace_id) and per-turn L4 recall snapshot."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from palatium_ai.application.services.memory_recall import recall_for_thread
from palatium_ai.core.logging import bind_turn_log_context, session_id_var, turn_id_var
from palatium_ai.core.logging.processors import add_context_vars
from palatium_ai.domain.graph.write_port import GraphFactRecord
from palatium_ai.domain.memory.scoring import lexical_relevance


class _GraphStub:
    """Records the ``as_of`` it was asked for; returns fixed active facts."""

    def __init__(self, facts: list[GraphFactRecord]) -> None:
        self._facts = facts
        self.as_of_seen: list[datetime | None] = []

    async def list_active_facts(
        self,
        *,
        user_id: str,
        limit: int = 8,
        as_of: datetime | None = None,
        thread_id: str | None = None,
    ) -> list[GraphFactRecord]:
        _ = (user_id, limit, thread_id)
        self.as_of_seen.append(as_of)
        return list(self._facts)


def _fact(key: str, text: str, *, kind: str = "fact", importance: float = 0.9) -> GraphFactRecord:
    return GraphFactRecord(
        node_id=f"n-{key}",
        user_id="u1",
        entry_key=key,
        text=text,
        kind=kind,
        importance=importance,
        confidence=0.9,
        created_at=datetime.now(UTC) - timedelta(days=1),
    )


@pytest.mark.asyncio()
async def test_graph_recall_drops_unrelated_facts_and_pins_as_of() -> None:
    """Regression: L4 facts were ranked by stored importance only, so a promoted
    fact from an unrelated task rode into every turn."""
    graph = _GraphStub(
        [
            _fact("old", "Ремонт дороги на улице Ленина запланирован на май", importance=0.99),
            _fact("doc", "Договор охраны массового мероприятия подписан"),
            _fact("pref", "Отвечать кратко", kind="preference"),
        ]
    )
    snapshot = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    bundle = await recall_for_thread(
        None,
        thread_id="t1",
        query="анекдот про охрану мероприятия",
        user_id="u1",
        graph_write=graph,  # type: ignore[arg-type]  # structural stub of GraphWritePort
        as_of=snapshot,
    )
    texts = [hit.text for hit in bundle.hits]
    assert "Договор охраны массового мероприятия подписан" in texts
    assert "Отвечать кратко" in texts
    assert all("Ремонт дороги" not in text for text in texts)
    assert graph.as_of_seen == [snapshot]
    assert all(hit.source == "graph" for hit in bundle.hits)


def test_lexical_relevance_matches_inflected_forms() -> None:
    assert lexical_relevance("что в документе", "Документ подписан") > 0.0
    assert lexical_relevance("анекдот", "Ремонт дороги") == 0.0
    assert lexical_relevance("", "anything") == 0.0


def test_turn_log_context_stamps_session_and_turn_then_resets() -> None:
    with bind_turn_log_context(session_id="thread-1", turn_id="turn-1"):
        event = add_context_vars(None, "info", {"event": "x"})  # type: ignore[arg-type]  # logger unused
        assert event["session_id"] == "thread-1"
        assert event["turn_id"] == "turn-1"
        explicit = add_context_vars(None, "info", {"event": "y", "turn_id": "other"})  # type: ignore[arg-type]  # logger unused
        assert explicit["turn_id"] == "other"
    assert session_id_var.get() is None
    assert turn_id_var.get() is None
