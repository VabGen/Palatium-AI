# tests/unit/test_document_ingest_service.py

"""DocumentIngestService facade over TextIngestor + HITL commit."""

from __future__ import annotations

import pytest

from palatium_ai.application.agents.evals.static_llm import StaticLLMPort
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.text_ingestor import TEXT_INGESTOR_CONFIG, TextIngestorAgent
from palatium_ai.application.services.document_ingest_service import DocumentIngestService
from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.domain.hitl.cards import HITLCardView
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler
from tests.conftest import PlatformKnowledgeMcpRegistry, make_document_ingest_stack


@pytest.fixture
def knowledge_port() -> InMemoryKnowledgePort:
    return InMemoryKnowledgePort()


@pytest.fixture
def ingest_service(knowledge_port: InMemoryKnowledgePort) -> DocumentIngestService:
    llm = StaticLLMPort('{"prefixes": ["Intro section about onboarding.", "Security section about passwords."]}')
    harness = Harness(llm=llm)
    hitl = HitlService(InMemoryHitlCardStore(), signing_secret="unit-test-hitl-hmac-key-32bytes!!")
    handler = PlatformToolHandler(knowledge_port=knowledge_port)
    return DocumentIngestService(
        harness=harness,
        text_ingestor=TextIngestorAgent(harness, TEXT_INGESTOR_CONFIG),
        hitl_service=hitl,
        mcp_registry=PlatformKnowledgeMcpRegistry(handler),
    )


@pytest.mark.asyncio
async def test_document_ingest_service_prepare_chunks(ingest_service: DocumentIngestService) -> None:
    result = await ingest_service.prepare_chunks(
        task_id="ingest-1",
        thread_id="thread-9",
        raw_text="Onboarding basics.\n\nPassword policy details.",
        enrich_context_prefix=True,
        document_title="Employee Handbook",
    )
    assert result.status == "success"
    assert result.output is not None
    assert result.output.context_prefixes_applied is True
    assert all(chunk.contextual_prefix for chunk in result.output.chunks)


@pytest.mark.asyncio
async def test_document_ingest_request_commit_and_execute(
    knowledge_port: InMemoryKnowledgePort,
) -> None:
    ingest, knowledge, _hitl, _handler = make_document_ingest_stack(knowledge_port)
    prepare = await ingest.prepare_chunks(  # type: ignore[attr-defined]
        task_id="prep-42",
        thread_id="thread-9",
        raw_text="Alpha.\n\nBeta.",
    )
    assert prepare.output is not None
    card = await ingest.request_commit(  # type: ignore[attr-defined]
        prepare_task_id="prep-42",
        owner_user_id="user-1",
        org_id="org-1",
    )
    assert isinstance(card, HITLCardView)
    assert card.task_id.startswith("doc-ingest-")
    outcome = await ingest.execute_after_approval(task_id=card.task_id)  # type: ignore[attr-defined]
    assert outcome["chunk_count"] == len(prepare.output.chunks)
    assert len(knowledge.documents) == 1  # type: ignore[attr-defined]
    assert knowledge.documents[0].chunk_count == len(prepare.output.chunks)  # type: ignore[attr-defined]
