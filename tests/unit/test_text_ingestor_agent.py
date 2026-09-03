# tests/unit/test_text_ingestor_agent.py

"""Unit tests for TextIngestor deterministic chunking."""

from __future__ import annotations

from uuid import uuid4

import pytest

from palatium_ai.application.agents.evals.static_llm import StaticLLMPort
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.text_ingestor import TEXT_INGESTOR_CONFIG, TextIngestorAgent
from palatium_ai.application.agents.text_ingestor.chunking import chunk_text, normalize_text
from palatium_ai.domain.agents.messages import AgentInput
from palatium_ai.domain.agents.text_ingestor import TextIngestorOutput


def test_normalize_text_collapses_blank_lines() -> None:
    assert normalize_text("a\n\n\n\nb") == "a\n\nb"


def test_chunk_text_paragraph_strategy() -> None:
    strategy, chunks = chunk_text("one\n\ntwo", max_chars=200)
    assert strategy == "paragraph"
    assert len(chunks) == 2


@pytest.mark.asyncio
async def test_text_ingestor_agent_via_harness() -> None:
    harness = Harness(llm=StaticLLMPort("{}"))
    agent = TextIngestorAgent(harness, TEXT_INGESTOR_CONFIG)
    output = await harness.execute_with_guardrails(
        agent,
        AgentInput(
            task_id=uuid4(),
            trace_id="test-trace",
            instruction="chunk document",
            context={
                "task_id": "ti-unit",
                "thread_id": "thread-1",
                "raw_text": "Alpha paragraph.\n\nBeta paragraph.",
                "max_chunk_chars": "500",
            },
        ),
    )
    assert output.status == "success"
    assert isinstance(output.output, TextIngestorOutput)
    assert len(output.output.chunks) == 2
    assert output.output.chunking_strategy == "paragraph"


@pytest.mark.asyncio
async def test_text_ingestor_context_prefix_via_harness() -> None:
    llm = StaticLLMPort('{"prefixes": ["From policy section A.", "From policy section B."]}')
    harness = Harness(llm=llm)
    agent = TextIngestorAgent(harness, TEXT_INGESTOR_CONFIG)
    output = await harness.execute_with_guardrails(
        agent,
        AgentInput(
            task_id=uuid4(),
            trace_id="test-trace",
            instruction="chunk document",
            context={
                "task_id": "ti-prefix",
                "thread_id": "thread-1",
                "raw_text": "Section A.\n\nSection B.",
                "max_chunk_chars": "500",
                "enrich_context_prefix": "true",
                "document_title": "Policy",
            },
        ),
    )
    assert output.status == "success"
    assert isinstance(output.output, TextIngestorOutput)
    assert output.output.context_prefixes_applied is True
    assert all(chunk.contextual_prefix for chunk in output.output.chunks)
