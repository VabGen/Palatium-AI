# tests/unit/test_text_ingestor_bridge.py

"""Bridge helpers for TextIngestor off-graph ingest path."""

from __future__ import annotations

import pytest

from palatium_ai.application.agents.evals.static_llm import StaticLLMPort
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.text_ingestor import TEXT_INGESTOR_CONFIG, TextIngestorAgent
from palatium_ai.application.orchestration.agent_bridge import (
    text_ingestor_output_to_task_result,
    text_ingestor_to_agent_input,
)
from palatium_ai.domain.agents.text_ingestor import TextIngestorInput, TextIngestorOutput


def test_text_ingestor_to_agent_input_maps_flags() -> None:
    task_input = TextIngestorInput(
        task_id="ti-1",
        thread_id="thread-1",
        raw_text="hello",
        enrich_context_prefix=True,
        document_title="Policy",
    )
    agent_input = text_ingestor_to_agent_input(task_input, trace_id="trace-1", thread_id="thread-1")
    assert agent_input.context["enrich_context_prefix"] == "true"
    assert agent_input.context["document_title"] == "Policy"


@pytest.mark.asyncio
async def test_text_ingestor_output_to_task_result_roundtrip() -> None:
    harness = Harness(llm=StaticLLMPort("{}"))
    agent = TextIngestorAgent(harness, TEXT_INGESTOR_CONFIG)
    agent_input = text_ingestor_to_agent_input(
        TextIngestorInput(task_id="ti-2", thread_id="thread-2", raw_text="one\n\ntwo"),
        trace_id="trace-2",
        thread_id="thread-2",
    )
    agent_output = await harness.execute_with_guardrails(agent, agent_input)
    result = text_ingestor_output_to_task_result(
        agent_output,
        task_id="ti-2",
        agent_role=agent.config.role,
    )
    assert result.status == "success"
    assert isinstance(result.output, TextIngestorOutput)
    assert len(result.output.chunks) == 2
