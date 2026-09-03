# tests/unit/test_knowledge_search.py

"""Knowledge hybrid search: scoring, in-memory port, platform handler."""

from __future__ import annotations

import json

import pytest

from palatium_ai.domain.agents.text_ingestor import TextChunk
from palatium_ai.domain.knowledge.scoring import merge_hybrid_knowledge_hits
from palatium_ai.domain.knowledge.types import IngestDocumentCommand, SearchKnowledgeQuery
from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler


def test_merge_hybrid_knowledge_hits_prefers_vector_overlap() -> None:
    fts = [("chunk-1", 0.8, {"text": "alpha"})]
    vector = [("chunk-1", 1.0, {"text": "alpha"}), ("chunk-2", 0.9, {"text": "beta"})]
    merged = merge_hybrid_knowledge_hits(fts, vector, limit=2)
    assert len(merged) == 2
    assert merged[0]["text"] == "alpha"
    assert float(merged[0]["score"]) > float(merged[1]["score"])


@pytest.mark.asyncio
async def test_in_memory_search_knowledge_token_overlap() -> None:
    port = InMemoryKnowledgePort()
    await port.ingest_document(
        IngestDocumentCommand(
            user_id="user-1",
            thread_id="thread-a",
            document_title="Handbook",
            chunks=(
                TextChunk(index=0, text="Password policy requires rotation every 90 days.", char_start=0, char_end=48),
                TextChunk(index=1, text="Onboarding checklist for new hires.", char_start=0, char_end=35),
            ),
        )
    )
    result = await port.search_knowledge(SearchKnowledgeQuery(user_id="user-1", query="password rotation", limit=4))
    assert len(result.hits) == 1
    assert "Password" in result.hits[0].text
    assert result.hits[0].document_title == "Handbook"


@pytest.mark.asyncio
async def test_platform_handler_search_knowledge() -> None:
    knowledge = InMemoryKnowledgePort()
    handler = PlatformToolHandler(knowledge_port=knowledge)
    await handler.call_tool(
        "ingest_document",
        {
            "user_id": "user-1",
            "thread_id": "thread-1",
            "chunks_json": json.dumps([{"index": 0, "text": "Neo4j graph consolidation rules."}]),
        },
    )
    result = await handler.call_tool(
        "search_knowledge",
        {"user_id": "user-1", "query": "graph consolidation", "limit": "5"},
    )
    assert result.is_error is False
    payload = json.loads(result.content[0]["text"])
    assert payload["hit_count"] == 1
    assert payload["hits"][0]["text"].startswith("Neo4j")
