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


def test_merge_hybrid_knowledge_hits_rrf_ranks_not_raw_scores() -> None:
    """RRF ignores raw scores: a weak FTS #1 can still lift a mid vector hit."""
    fts = [("only-fts", 0.99, {"text": "fts"}), ("both", 0.1, {"text": "both"})]
    vector = [("only-vec", 0.99, {"text": "vec"}), ("both", 0.5, {"text": "both"})]
    merged = merge_hybrid_knowledge_hits(fts, vector, limit=3, fusion="rrf", rrf_k=60)
    assert [hit["text"] for hit in merged] == ["both", "fts", "vec"]
    # Appears in both lists → higher RRF than either singleton.
    assert float(merged[0]["score"]) > float(merged[1]["score"])
    assert float(merged[1]["score"]) == float(merged[2]["score"])
    # RRF is not unit-clamped: 1/(60+1)+1/(60+2) ≈ 0.0325.
    assert 0.03 < float(merged[0]["score"]) < 0.04


def test_knowledge_config_accepts_rrf_fusion() -> None:
    from palatium_ai.core.config.knowledge import KnowledgeConfig

    cfg = KnowledgeConfig.model_validate({"KNOWLEDGE_HYBRID_FUSION": "rrf", "KNOWLEDGE_RRF_K": 40})
    assert cfg.hybrid_fusion == "rrf"
    assert cfg.rrf_k == 40


@pytest.mark.asyncio()
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


@pytest.mark.asyncio()
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


@pytest.mark.asyncio()
async def test_embedding_rerank_knowledge_port_reorders_by_cosine() -> None:
    from uuid import uuid4

    from palatium_ai.domain.knowledge.types import KnowledgeSearchHit, KnowledgeSearchResult
    from palatium_ai.infrastructure.knowledge.embedding_rerank import EmbeddingRerankKnowledgePort

    class _Inner:
        async def ingest_document(self, command):
            raise NotImplementedError

        async def search_knowledge(self, query: SearchKnowledgeQuery) -> KnowledgeSearchResult:
            assert query.limit == 6  # overfetch 3 × limit 2
            return KnowledgeSearchResult(
                query=query.query,
                hits=(
                    KnowledgeSearchHit(
                        chunk_id=uuid4(),
                        document_id=uuid4(),
                        chunk_index=0,
                        text="unrelated weather notes",
                        thread_id="t1",
                        score=0.9,
                    ),
                    KnowledgeSearchHit(
                        chunk_id=uuid4(),
                        document_id=uuid4(),
                        chunk_index=1,
                        text="password rotation policy",
                        thread_id="t1",
                        score=0.2,
                    ),
                ),
            )

    class _Emb:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            # Query and target share a direction; weather is orthogonal.
            mapping = {
                "password": [1.0, 0.0],
                "weather": [0.0, 1.0],
            }
            out: list[list[float]] = []
            for text in texts:
                key = "password" if "password" in text.lower() else "weather"
                # First vector is the query ("password rotation").
                if text.lower().startswith("password") and "policy" not in text.lower():
                    out.append(mapping["password"])
                else:
                    out.append(mapping[key])
            return out

    port = EmbeddingRerankKnowledgePort(_Inner(), _Emb(), overfetch=3)
    result = await port.search_knowledge(SearchKnowledgeQuery(user_id="u1", query="password rotation", limit=2))
    assert result.hits[0].text == "password rotation policy"
    assert float(result.hits[0].score) >= float(result.hits[1].score)
