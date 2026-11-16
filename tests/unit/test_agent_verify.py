"""Rule-based agent.verify() gates (030.7 / audit P0 / W4)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from palatium_ai.application.agents.analyst import ANALYST_CONFIG, AnalystAgent
from palatium_ai.application.agents.coder import CODER_CONFIG, CoderAgent
from palatium_ai.application.agents.critic import CRITIC_CONFIG, CriticAgent
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.intent_classifier import INTENT_CLASSIFIER_CONFIG, IntentClassifierAgent
from palatium_ai.application.agents.memory_keeper import MEMORY_KEEPER_CONFIG, MemoryKeeperAgent
from palatium_ai.application.agents.researcher import RESEARCHER_CONFIG, ResearcherAgent
from palatium_ai.application.agents.researcher.parsing import FAILURE_PLACEHOLDER_SUMMARY
from palatium_ai.application.agents.supervisor import SUPERVISOR_CONFIG, SupervisorAgent
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.coder import CoderOutput
from palatium_ai.domain.agents.critic import CriticOutput
from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.agents.memory_keeper import MemoryFactCandidate, MemoryKeeperOutput
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.agents.researcher import ResearcherOutput
from palatium_ai.domain.agents.supervisor import SupervisorOutput
from palatium_ai.domain.llm.models import LLMCompletion, LLMUsage


class _StubLLM:
    async def generate(self, *args: object, **kwargs: object) -> LLMCompletion:
        _ = args, kwargs
        return LLMCompletion(content="{}", usage=LLMUsage())


@pytest.mark.asyncio()
async def test_researcher_verify_rejects_grounded_without_sources() -> None:
    harness = Harness(llm=_StubLLM())
    agent = ResearcherAgent(harness, RESEARCHER_CONFIG, _StubLLM())
    ok = await agent.verify(
        AgentOutput(
            task_id=uuid4(),
            status="success",
            confidence=0.9,
            output=ResearcherOutput(
                summary="Claim with no evidence",
                confidence=0.9,
                sources_used=(),
                grounding_satisfied=True,
            ),
        ),
    )
    assert ok is False


@pytest.mark.asyncio()
async def test_researcher_verify_rejects_placeholder_summary() -> None:
    harness = Harness(llm=_StubLLM())
    agent = ResearcherAgent(harness, RESEARCHER_CONFIG, _StubLLM())
    ok = await agent.verify(
        AgentOutput(
            task_id=uuid4(),
            status="success",
            confidence=0.5,
            output=ResearcherOutput(summary=FAILURE_PLACEHOLDER_SUMMARY, confidence=0.5),
        ),
    )
    assert ok is False


@pytest.mark.asyncio()
async def test_intent_verify_rejects_social_with_required_grounding() -> None:
    harness = Harness(llm=_StubLLM())
    agent = IntentClassifierAgent(harness, INTENT_CLASSIFIER_CONFIG)
    ok = await agent.verify(
        AgentOutput(
            task_id=uuid4(),
            status="success",
            confidence=0.9,
            output=IntentClassifierOutput(
                task_kind="social_conversation",
                requires_mcp=False,
                grounding="required",
                confidence=0.9,
                reasoning="inconsistent",
            ),
        ),
    )
    assert ok is False


@pytest.mark.asyncio()
async def test_memory_keeper_verify_rejects_whitespace_only_fact() -> None:
    harness = Harness(llm=_StubLLM())
    agent = MemoryKeeperAgent(harness, MEMORY_KEEPER_CONFIG)
    # Bypass Field(min_length=1) to simulate a slipped whitespace-only candidate.
    fact = MemoryFactCandidate.model_construct(text="   ", kind="fact", confidence=0.9)
    ok = await agent.verify(
        AgentOutput(
            task_id=uuid4(),
            status="success",
            confidence=0.9,
            output=MemoryKeeperOutput.model_construct(facts=(fact,), reasoning=""),
        ),
    )
    assert ok is False


@pytest.mark.asyncio()
async def test_coder_verify_rejects_whitespace_summary() -> None:
    harness = Harness(llm=_StubLLM())
    agent = CoderAgent(harness, CODER_CONFIG)
    ok = await agent.verify(
        AgentOutput(
            task_id=uuid4(),
            status="success",
            confidence=0.9,
            output=CoderOutput.model_construct(summary="   ", confidence=0.9),
        ),
    )
    assert ok is False


@pytest.mark.asyncio()
async def test_analyst_verify_rejects_mistyped_payload() -> None:
    harness = Harness(llm=_StubLLM())
    agent = AnalystAgent(harness, ANALYST_CONFIG)
    ok = await agent.verify(
        AgentOutput(
            task_id=uuid4(),
            status="success",
            confidence=0.9,
            output=ResearcherOutput(summary="wrong type", confidence=0.9),
        ),
    )
    assert ok is False


@pytest.mark.asyncio()
async def test_supervisor_verify_rejects_route_target_mismatch() -> None:
    harness = Harness(llm=_StubLLM())
    agent = SupervisorAgent(harness, SUPERVISOR_CONFIG)
    ok = await agent.verify(
        AgentOutput(
            task_id=uuid4(),
            status="success",
            confidence=0.9,
            output=SupervisorOutput(
                route="researcher",
                target_agent="formatter",
                confidence=0.9,
                plan="broken pairing",
            ),
        ),
    )
    assert ok is False


@pytest.mark.asyncio()
async def test_critic_verify_rejects_violations_without_review() -> None:
    harness = Harness(llm=_StubLLM())
    agent = CriticAgent(harness, CRITIC_CONFIG)
    ok = await agent.verify(
        AgentOutput(
            task_id=uuid4(),
            status="success",
            confidence=0.9,
            output=CriticOutput.model_construct(
                accuracy_score=9,
                safety_score=9,
                requires_review=False,
                summary="looks fine",
                violations=("no_secret_echo",),
            ),
        ),
    )
    assert ok is False


@pytest.mark.asyncio()
async def test_harness_demotes_on_verify_failure() -> None:
    class _FailVerify(BaseAgent):
        def get_required_context_keys(self) -> list[str]:
            return []

        def get_available_tools(self) -> list[str]:
            return []

        async def run(self, input: AgentInput) -> AgentOutput:
            return AgentOutput(
                task_id=input.task_id,
                status="success",
                confidence=0.95,
                output=ResearcherOutput(summary="ok enough", confidence=0.95),
            )

        async def verify(self, output: AgentOutput) -> bool:
            _ = output
            return False

    harness = Harness()
    agent = _FailVerify(harness, RESEARCHER_CONFIG)
    before = agent_metrics.escalation_count("verify_failed_researcher")
    output = await harness.execute_with_guardrails(
        agent,
        AgentInput(task_id=uuid4(), trace_id="t", instruction="x"),
    )
    assert output.status == "partial"
    assert agent_metrics.escalation_count("verify_failed_researcher") == before + 1
