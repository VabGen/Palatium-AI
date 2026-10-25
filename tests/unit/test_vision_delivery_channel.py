"""Delivery channel for ``image_parts``: HTTP turn → graph state → agent → LLM call (ADR 0007).

The ADR pinned the message contract, the admission policy and the adapter route; this
module pins the seam in between, because that is where an image used to disappear:
the worker node built ``AgentInput`` from text-only fields, so an approved part had no
way to reach ``ChatMessage.image_parts``.

Covered here:
* ``AgentInput`` carries parts additively — no caller breaks, ``model_copy`` (the
  Harness' redaction/compaction path) keeps them;
* the graph admits once and every worker reads the same set from state;
* Researcher and Analyst put the parts on the *user* turn of the LLM call.
"""

from __future__ import annotations

import json

from uuid import uuid4

import pytest

from palatium_ai.application.agents.analyst import ANALYST_CONFIG, AnalystAgent
from palatium_ai.application.agents.evals.cassette import _packet_from_raw
from palatium_ai.application.agents.evals.static_llm import SequentialStaticLLMPort
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.researcher import RESEARCHER_CONFIG, ResearcherAgent
from palatium_ai.application.orchestration import selectors
from palatium_ai.application.orchestration.agent_bridge import (
    analyst_to_agent_input,
    researcher_to_agent_input,
)
from palatium_ai.domain.agents.analyst import AnalystInput
from palatium_ai.domain.agents.messages import AgentInput
from palatium_ai.domain.agents.researcher import ResearcherInput
from palatium_ai.domain.llm.models import ImagePart

_PACKET_RAW = {
    "user_text": "What does the chart show?",
    "task_kind": "knowledge_request",
    "route": "researcher",
    "requires_mcp": False,
    "requires_tool_call": False,
    "selected_strategy": "reason_only",
}


def _part() -> ImagePart:
    return ImagePart(attachment_id=uuid4(), mime="image/png")


def _input(*, image_parts: tuple[ImagePart, ...] = ()) -> AgentInput:
    return AgentInput(
        task_id=uuid4(),
        trace_id="vision-channel",
        instruction="What does the chart show?",
        image_parts=image_parts,
    )


def test_agent_input_defaults_to_no_images() -> None:
    """Every pre-existing caller (11 bridge builders, cassettes) stays valid unchanged."""
    assert _input().image_parts == ()


def test_model_copy_keeps_the_admitted_parts() -> None:
    """Harness redaction/compaction rebuilds ``AgentInput``; an image must survive it."""
    part = _part()
    updated = _input(image_parts=(part,)).model_copy(update={"instruction": "masked"})
    assert updated.image_parts == (part,)


def test_graph_state_exposes_one_admitted_set() -> None:
    part = _part()
    assert selectors.turn_image_parts({"image_parts": (part,)}) == (part,)


def test_legacy_checkpoint_has_no_images() -> None:
    """States written before S2c have no key at all; reading one must not raise."""
    assert selectors.turn_image_parts({}) == ()


def test_researcher_bridge_forwards_parts() -> None:
    part = _part()
    task_id = str(uuid4())
    packet = _packet_from_raw(_PACKET_RAW, task_id)
    built = researcher_to_agent_input(
        ResearcherInput(task_id=task_id, context_packet=packet),
        trace_id="vision-channel",
        thread_id="thread-1",
        image_parts=(part,),
    )
    assert built.image_parts == (part,)


@pytest.mark.asyncio()
async def test_researcher_puts_images_on_the_user_turn() -> None:
    """The ask carries the picture; the system prompt never does (injection boundary)."""
    part = _part()
    task_id = str(uuid4())
    packet = _packet_from_raw(_PACKET_RAW, task_id)
    llm = SequentialStaticLLMPort([json.dumps({"summary": "A bar chart.", "confidence": 0.9})])
    harness = Harness(llm=llm)
    agent = ResearcherAgent(harness, RESEARCHER_CONFIG, llm)

    output = await harness.execute_with_guardrails(
        agent,
        researcher_to_agent_input(
            ResearcherInput(task_id=task_id, context_packet=packet),
            trace_id="vision-channel",
            thread_id="thread-1",
            image_parts=(part,),
        ),
    )

    assert output.status != "failure", output.error_message
    assert llm.calls, "the researcher must reach the LLM"
    messages = llm.calls[0]
    user_turns = [message for message in messages if message.role == "user"]
    assert user_turns[0].image_parts == (part,)
    assert all(not message.image_parts for message in messages if message.role != "user")


@pytest.mark.asyncio()
async def test_analyst_puts_images_on_the_user_turn() -> None:
    part = _part()
    task_id = str(uuid4())
    packet = _packet_from_raw(_PACKET_RAW, task_id)
    llm = SequentialStaticLLMPort([json.dumps({"summary": "Bars grow left to right.", "confidence": 0.8})])
    harness = Harness(llm=llm)
    agent = AnalystAgent(harness, ANALYST_CONFIG)
    agent_input = analyst_to_agent_input(
        AnalystInput(task_id=task_id, context_packet=packet),
        trace_id="vision-channel",
        thread_id="thread-1",
        image_parts=(part,),
    )

    output = await harness.execute_with_guardrails(agent, agent_input)

    assert output.status != "failure", output.error_message
    user_turns = [message for message in llm.calls[0] if message.role == "user"]
    assert user_turns[0].image_parts == (part,)
