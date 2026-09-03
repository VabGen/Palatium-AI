# tests/unit/test_platform_knowledge_ingest.py

"""Platform ingest_document → KnowledgePort wiring."""

from __future__ import annotations

import json

import pytest

from palatium_ai.domain.agents.text_ingestor import TextChunk
from palatium_ai.domain.knowledge.types import IngestDocumentCommand
from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler


@pytest.mark.asyncio
async def test_platform_handler_persists_chunks() -> None:
    knowledge = InMemoryKnowledgePort()
    handler = PlatformToolHandler(knowledge_port=knowledge)
    chunks = [
        {"index": 0, "text": "Alpha", "contextual_prefix": "Intro"},
        {"index": 1, "text": "Beta", "contextual_prefix": "Body"},
    ]
    result = await handler.call_tool(
        "ingest_document",
        {
            "user_id": "user-1",
            "thread_id": "thread-1",
            "chunks_json": json.dumps(chunks),
            "document_id": "doc-ext-1",
        },
    )
    assert result.is_error is False
    assert len(knowledge.documents) == 1
    assert knowledge.documents[0].chunk_count == 2


@pytest.mark.asyncio
async def test_in_memory_knowledge_port_command() -> None:
    port = InMemoryKnowledgePort()
    result = await port.ingest_document(
        IngestDocumentCommand(
            user_id="user-2",
            thread_id="thread-2",
            chunks=(TextChunk(index=0, text="hello", char_start=0, char_end=5),),
        )
    )
    assert result.chunk_count == 1
    assert str(result.document_ref)
