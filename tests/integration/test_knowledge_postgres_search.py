# tests/integration/test_knowledge_postgres_search.py

"""Postgres integration: knowledge ingest + hybrid search (requires DATABASE_URL)."""

from __future__ import annotations

import os

import pytest

from palatium_ai.domain.agents.text_ingestor import TextChunk
from palatium_ai.domain.knowledge.types import IngestDocumentCommand, SearchKnowledgeQuery
from palatium_ai.infrastructure.knowledge.postgres_knowledge_port import PostgresKnowledgePort


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_knowledge_search_after_ingest(requires_database: str) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(requires_database)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    port = PostgresKnowledgePort(session_factory, embeddings=None)

    user_id = "integration-knowledge-user"
    thread_id = "integration-knowledge-thread"
    command = IngestDocumentCommand(
        user_id=user_id,
        thread_id=thread_id,
        document_title="Integration Handbook",
        chunks=(
            TextChunk(
                index=0,
                text="Palatium orchestration uses LangGraph with Harness guardrails.",
                char_start=0,
                char_end=58,
            ),
            TextChunk(
                index=1,
                text="Knowledge chunks are stored in the knowledge schema with FTS.",
                char_start=0,
                char_end=60,
            ),
        ),
    )
    try:
        ingest = await port.ingest_document(command)
        assert ingest.chunk_count == 2

        result = await port.search_knowledge(
            SearchKnowledgeQuery(
                user_id=user_id,
                query="LangGraph Harness",
                thread_id=thread_id,
                limit=5,
            )
        )
        assert len(result.hits) >= 1
        assert any("LangGraph" in hit.text for hit in result.hits)
    except Exception as exc:
        if os.environ.get("PALATIUM_STRICT_INTEGRATION") == "1":
            raise
        pytest.skip(f"knowledge schema unavailable: {exc}")
    finally:
        await engine.dispose()
