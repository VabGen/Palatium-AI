# tests/unit/test_knowledge_project_scope.py

"""Project KB search scoping (G09)."""

from __future__ import annotations

import pytest

from palatium_ai.domain.agents.text_ingestor import TextChunk
from palatium_ai.domain.knowledge.project_scope import project_source_document_prefix
from palatium_ai.domain.knowledge.types import IngestDocumentCommand, SearchKnowledgeQuery
from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort


def test_project_prefix_rejects_blank() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        project_source_document_prefix("  ")


@pytest.mark.asyncio()
async def test_in_memory_search_filters_by_project() -> None:
    port = InMemoryKnowledgePort()
    await port.ingest_document(
        IngestDocumentCommand(
            user_id="u1",
            thread_id="t1",
            document_id="project:alpha:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            document_title="Alpha",
            chunks=(TextChunk(index=0, text="alpha password rotation policy", char_start=0, char_end=30),),
        )
    )
    await port.ingest_document(
        IngestDocumentCommand(
            user_id="u1",
            thread_id="t1",
            document_id="project:beta:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            document_title="Beta",
            chunks=(TextChunk(index=0, text="beta password rotation policy", char_start=0, char_end=29),),
        )
    )

    scoped = await port.search_knowledge(
        SearchKnowledgeQuery(user_id="u1", query="password rotation", project_id="alpha", limit=8)
    )
    assert len(scoped.hits) == 1
    assert scoped.hits[0].document_title == "Alpha"

    all_hits = await port.search_knowledge(SearchKnowledgeQuery(user_id="u1", query="password rotation", limit=8))
    assert len(all_hits.hits) == 2


@pytest.mark.asyncio()
async def test_in_memory_search_filters_by_source_document_id() -> None:
    """Exact document_id filter prevents cross-file retrieval bleed."""
    port = InMemoryKnowledgePort()
    await port.ingest_document(
        IngestDocumentCommand(
            user_id="u1",
            thread_id="t1",
            document_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            document_title="webp",
            chunks=(TextChunk(index=0, text="иван чай цена выросла", char_start=0, char_end=22),),
        )
    )
    await port.ingest_document(
        IngestDocumentCommand(
            user_id="u1",
            thread_id="t1",
            document_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            document_title="pdf",
            chunks=(TextChunk(index=0, text="СФОТ банки отчёт по филиалам", char_start=0, char_end=28),),
        )
    )

    scoped = await port.search_knowledge(
        SearchKnowledgeQuery(
            user_id="u1",
            query="отчёт",
            source_document_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            limit=8,
        )
    )
    assert len(scoped.hits) == 1
    assert scoped.hits[0].document_title == "pdf"
    assert "иван чай" not in scoped.hits[0].text


@pytest.mark.asyncio()
async def test_in_memory_ingest_replaces_same_source_document_id() -> None:
    """Re-index must not leave duplicate near-identical chunks for one attachment."""
    port = InMemoryKnowledgePort()
    source = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    await port.ingest_document(
        IngestDocumentCommand(
            user_id="u1",
            thread_id="t1",
            document_id=source,
            document_title="v1",
            chunks=(TextChunk(index=0, text="old body about tea", char_start=0, char_end=18),),
        )
    )
    await port.ingest_document(
        IngestDocumentCommand(
            user_id="u1",
            thread_id="t1",
            document_id=source,
            document_title="v2",
            chunks=(TextChunk(index=0, text="new body about banks", char_start=0, char_end=20),),
        )
    )
    hits = await port.search_knowledge(SearchKnowledgeQuery(user_id="u1", query="body", limit=8))
    assert len(hits.hits) == 1
    assert hits.hits[0].document_title == "v2"
    assert "banks" in hits.hits[0].text
