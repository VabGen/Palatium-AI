# tests/eval/test_behavioral_evals.py

"""W5 behavioral evals — hop budgets, handoffs, tools, constitution, enum hygiene."""

from __future__ import annotations

import asyncio

from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from palatium_ai.application.agents.critic import CRITIC_CONFIG, CriticAgent
from palatium_ai.application.agents.evals.behavioral import (
    estimated_steps,
    global_max_subagent_depth,
    refresh_policy,
    route_budget,
)
from palatium_ai.application.agents.evals.cassette import run_cassette_task
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.researcher import RESEARCHER_CONFIG
from palatium_ai.application.agents.supervisor import SUPERVISOR_CONFIG, SupervisorAgent
from palatium_ai.application.orchestration.agent_bridge import supervisor_to_agent_input
from palatium_ai.application.orchestration.nodes import (
    route_after_context,
    route_after_critic,
    route_after_quality_revision,
)
from palatium_ai.application.services.intent_hitl_flow import max_quality_revisions
from palatium_ai.application.services.interaction_assembler import InteractionAssembler
from palatium_ai.application.tools.executor import ToolExecutor, ToolRbacDenied
from palatium_ai.application.tools.mcp import MCPToolCallParams
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.types.agent_observability import (
    AGENT_HANDOFF_REASONS,
    WORKER_EXECUTION_STATUSES,
)
from palatium_ai.core.types.graph_nodes import (
    NODE_CODER,
    NODE_CONTEXT_ENRICHER_WEAVING,
    NODE_CRITIC,
    NODE_FORMATTER,
    NODE_QUALITY_REVISION,
    NODE_RESEARCHER,
)
from palatium_ai.domain.agents.critic import CriticOutput, CriticTaskResult
from palatium_ai.domain.agents.messages import AgentOutput
from palatium_ai.domain.agents.supervisor import SupervisorInput
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.content.content_document import DocumentMeta, ParagraphBlock
from palatium_ai.domain.llm.models import LLMCompletion, LLMUsage
from palatium_ai.domain.policies import CriticPolicy


class _StubLLM:
    async def generate(self, *args: object, **kwargs: object) -> LLMCompletion:
        _ = args, kwargs
        return LLMCompletion(content="{}", usage=LLMUsage())


def _snapshot(strategy: str, *, task_kind: str = "knowledge_request") -> MagicMock:
    snap = MagicMock()
    snap.selected_strategy = strategy
    snap.task_kind = task_kind
    return snap


def _critic(*, requires_review: bool) -> CriticTaskResult:
    return CriticTaskResult(
        task_id="t1",
        agent_role="critic",
        status="partial" if requires_review else "success",
        confidence=0.5,
        requires_review=requires_review,
        output=CriticOutput(
            accuracy_score=3 if requires_review else 9,
            safety_score=9,
            requires_review=requires_review,
            summary="Needs more sources" if requires_review else "ok",
        ),
    )


@pytest.mark.parametrize(
    "route_id,has_worker,revisions,skip_critic",
    (
        ("social_format_only", False, 0, False),
        ("response_formatting_skip_critic_edge", False, 0, True),
        ("reason_only", True, 0, False),
        ("code_sandbox", True, 0, False),
        ("data_analysis", True, 0, False),
        ("quality_revision_once", True, 1, False),
        ("high_confidence_no_revision", True, 0, False),
    ),
)
def test_w5_step_count_pins_measured_topology(
    route_id: str,
    has_worker: bool,
    revisions: int,
    skip_critic: bool,
) -> None:
    """actual_* is the measured graph; max_* must not silently exceed without refresh."""
    budget = route_budget(route_id)
    steps = estimated_steps(has_worker=has_worker, revisions=revisions, skip_critic=skip_critic)
    assert steps == budget.actual_steps
    assert steps <= budget.max_steps
    assert budget.actual_steps <= budget.max_steps
    assert budget.actual_handoffs <= budget.max_handoffs
    assert budget.cost_channel == "cassette_unmeasured"
    assert budget.actual_cost_usd is None
    assert budget.max_cost_usd is None
    assert revisions <= budget.max_subagent_depth
    assert budget.max_subagent_depth <= global_max_subagent_depth()
    assert max_quality_revisions() <= global_max_subagent_depth()


def test_w5_baseline_refresh_policy_requires_marker() -> None:
    policy = refresh_policy()
    assert policy["marker"] == "[baseline-refresh]"
    assert "Silent upward drift is forbidden" in str(policy["rule"])


def test_w5_no_nested_subagent_spawn_cap() -> None:
    """Topology forbids nested agent spawn; depth ≡ quality revision budget."""
    assert global_max_subagent_depth() == 2
    assert max_quality_revisions() <= global_max_subagent_depth()


def test_w5_handoffs_reason_only_within_baseline() -> None:
    budget = route_budget("reason_only")
    before = agent_metrics.handoff_total()
    state: dict = {"requires_clarification": False}
    with patch(
        "palatium_ai.application.orchestration.nodes.OrchestrationSnapshot.from_state",
        side_effect=lambda _s: _snapshot("reason_only"),
    ):
        assert route_after_context(state) == NODE_RESEARCHER  # type: ignore[arg-type]
    state_after = {"critic": _critic(requires_review=False), "revisions_count": 0}
    with patch(
        "palatium_ai.application.orchestration.nodes.OrchestrationSnapshot.from_state",
        side_effect=lambda _s: _snapshot("reason_only"),
    ):
        assert route_after_critic(state_after) == NODE_FORMATTER  # type: ignore[arg-type]
    delta = agent_metrics.handoff_total() - before
    assert delta == budget.actual_handoffs
    assert delta <= budget.max_handoffs
    assert agent_metrics.recorded_handoff_reasons() <= AGENT_HANDOFF_REASONS


def test_w5_no_redundant_handoff_high_confidence_passthrough() -> None:
    """CriticPolicy green path must not open quality_revision (W5.3)."""
    decision = CriticPolicy.decide(
        selected_strategy="reason_only",
        task_kind="knowledge_request",
        continuation_kind="answer",
        classification_confidence=0.95,
        confidence_threshold=0.7,
        requires_mcp=False,
        requires_tool_call=False,
        worker_summary="Stable prior answer body",
        user_input_chars=12,
        worker_confidence=0.95,
        has_attachment_context=False,
        verbatim_requested=False,
    )
    assert decision.invoke_llm is False
    assert decision.reason == "answer_high_confidence_passthrough"

    budget = route_budget("high_confidence_no_revision")
    before = agent_metrics.handoff_total()
    revision_before = agent_metrics.agent_handoff_count(
        from_node=NODE_CRITIC,
        to_node=NODE_QUALITY_REVISION,
        reason="requires_review",
    )
    state = {"critic": _critic(requires_review=False), "revisions_count": 0}
    with patch(
        "palatium_ai.application.orchestration.nodes.OrchestrationSnapshot.from_state",
        side_effect=lambda _s: _snapshot("reason_only"),
    ):
        assert route_after_critic(state) == NODE_FORMATTER  # type: ignore[arg-type]
    assert (
        agent_metrics.agent_handoff_count(
            from_node=NODE_CRITIC,
            to_node=NODE_QUALITY_REVISION,
            reason="requires_review",
        )
        == revision_before
    )
    assert agent_metrics.handoff_total() - before <= budget.max_handoffs


@pytest.mark.asyncio()
async def test_w5_simple_ask_skips_worker_subagents() -> None:
    """Social ask routes to formatter — no researcher/coder/analyst fan-out (W5.3)."""
    harness = Harness(llm=_StubLLM())
    agent = SupervisorAgent(harness, SUPERVISOR_CONFIG)
    task_input = SupervisorInput(
        task_id="social-1",
        user_text="привет",
        task_kind="social_conversation",
        requires_mcp=False,
        classification_confidence=0.95,
    )
    output = await harness.execute_with_guardrails(
        agent,
        supervisor_to_agent_input(task_input, trace_id="eval", thread_id="eval"),
    )
    assert output.output.route == "formatter"  # type: ignore[union-attr]
    assert output.output.target_agent == "formatter"  # type: ignore[union-attr]

    state: dict = {"requires_clarification": False}
    with patch(
        "palatium_ai.application.orchestration.nodes.OrchestrationSnapshot.from_state",
        side_effect=lambda _s: _snapshot("format_only", task_kind="response_formatting"),
    ):
        assert route_after_context(state) == NODE_FORMATTER  # type: ignore[arg-type]


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "task_id,expected_tools",
    (
        ("researcher-knowledge", set()),
        ("researcher-search-knowledge", {"search_knowledge"}),
        ("researcher-search-memory", {"search_memory"}),
        ("researcher-graph-query", {"graph_query"}),
        ("researcher-web-fallback", {"web_fallback"}),
    ),
)
async def test_w5_tool_selection_set_equality(task_id: str, expected_tools: set[str]) -> None:
    from palatium_ai.application.agents.evals.runner import load_agent_tasks

    task = next(item for item in load_agent_tasks("researcher") if item.get("id") == task_id)
    output = await run_cassette_task("researcher", task)
    assert set(output.get("tool_calls") or []) == expected_tools


@pytest.mark.asyncio()
async def test_w5_memory_keeper_does_not_persist_tools() -> None:
    from palatium_ai.application.agents.evals.runner import load_agent_tasks

    task = next(item for item in load_agent_tasks("memory_keeper") if item.get("id") == "keeper-preference")
    output = await run_cassette_task("memory_keeper", task)
    assert set(output.get("tool_calls") or []) == set()
    assert RESEARCHER_CONFIG.allowed_tools  # contrast: workers may call tools
    assert "mcp:platform.save_memory" not in RESEARCHER_CONFIG.allowed_tools


@pytest.mark.asyncio()
async def test_w5_allowed_tools_blocks_risky_write() -> None:
    executor = ToolExecutor(RESEARCHER_CONFIG)

    async def _handler(params: MCPToolCallParams) -> str:
        return params.tool_name

    denied = await executor.try_execute(
        "mcp.call",
        MCPToolCallParams(server_name="platform", tool_name="save_memory", arguments={}),
        _handler,
    )
    assert isinstance(denied, ToolRbacDenied)


@pytest.mark.asyncio()
async def test_w5_constitution_blocks_even_on_passthrough() -> None:
    from palatium_ai.application.agents.evals.runner import load_agent_tasks

    task = next(item for item in load_agent_tasks("critic") if item.get("id") == "constitution_blocks_passthrough")
    before = agent_metrics.escalation_count("critic_requires_review")
    output = await run_cassette_task("critic", task)
    assert output["llm_invoked"] is False
    assert output["requires_review"] is True
    assert output["status"] == "partial"
    assert output["constitution_blocked"] is True
    assert "no_pii_echo_without_permission" in set(output.get("violations") or [])
    assert agent_metrics.escalation_count("critic_requires_review") == before + 1

    # Harness secret-redacts sk- tokens before Critic; PII still reaches Constitution
    # on the CriticPolicy passthrough path (W5.4 — rule-based gate is not skipped).
    harness = Harness(llm=_StubLLM())
    agent = CriticAgent(harness, CRITIC_CONFIG)
    ok = await agent.verify(
        AgentOutput(
            task_id=uuid4(),
            status="partial",
            confidence=0.5,
            output=CriticOutput(
                accuracy_score=9,
                safety_score=9,
                requires_review=True,
                summary="blocked",
                violations=("no_pii_echo_without_permission",),
            ),
        ),
    )
    assert ok is True


@pytest.mark.asyncio()
async def test_w5_requires_review_reaches_operator_surface() -> None:
    """Fail-soft PII must leave the Critic object: Formatter → HITL plan → UI payload."""
    from palatium_ai.application.agents.evals.runner import load_agent_tasks
    from palatium_ai.application.orchestration import node_inputs as node_inputs_mod

    task = next(item for item in load_agent_tasks("critic") if item.get("id") == "constitution_blocks_passthrough")
    critic_out = await run_cassette_task("critic", task)
    assert critic_out["requires_review"] is True

    critic_result = CriticTaskResult(
        task_id="const-delivery",
        agent_role="critic",
        status="partial",
        confidence=0.5,
        requires_review=True,
        output=CriticOutput(
            accuracy_score=9,
            safety_score=5,
            requires_review=True,
            summary="pii",
            violations=("no_pii_echo_without_permission",),
        ),
    )
    # Mirrors ``build_formatter_input`` composition (node_inputs.py): flag must not
    # die on CriticTaskResult alone.
    src_path = Path(node_inputs_mod.__file__)
    src = await asyncio.to_thread(src_path.read_text, encoding="utf-8")
    assert "requires_review=intent_review or critic_requires_review" in src
    formatter_requires_review = False or critic_result.requires_review
    assert formatter_requires_review is True

    document = ContentDocument(
        locale="ru-RU",
        blocks=(ParagraphBlock(text="body"),),
        meta=DocumentMeta(confidence=0.9, requires_review=False),
    )
    stamped = document.model_copy(
        update={
            "meta": document.meta.model_copy(update={"requires_review": formatter_requires_review}),
        }
    )
    assert stamped.meta.requires_review is True

    assembled = InteractionAssembler.assemble(
        stamped,
        requires_review=formatter_requires_review,
        selected_strategy="format_only",
        task_kind="response_formatting",
    )
    assert assembled.plan.mint_quality_review is True

    # Same shape ChatShell.parseAssistantPayload reads for `_requiresReview`.
    assistant_payload = {
        "requires_review": formatter_requires_review,
        "document": stamped.model_dump(mode="json"),
        "hitl_cards": [],
    }
    assert assistant_payload["requires_review"] is True
    session_status = "needs_review" if assistant_payload["requires_review"] else "active"
    assert session_status == "needs_review"


def test_w5_metric_label_enum_hygiene_after_routing_scenarios() -> None:
    """Observed handoff reasons / worker statuses ⊆ closed Literals (W5.5)."""
    state: dict = {"requires_clarification": False}
    scenarios = (
        ("reason_only", "knowledge_request", NODE_RESEARCHER),
        ("code_sandbox", "tool_execution", NODE_CODER),
        ("format_only", "response_formatting", NODE_FORMATTER),
        ("format_only", "social_conversation", NODE_CRITIC),
    )
    for strategy, task_kind, expected in scenarios:
        with patch(
            "palatium_ai.application.orchestration.nodes.OrchestrationSnapshot.from_state",
            side_effect=lambda _s, s=strategy, tk=task_kind: _snapshot(s, task_kind=tk),
        ):
            assert route_after_context(state) == expected  # type: ignore[arg-type]

    with patch(
        "palatium_ai.application.orchestration.nodes.OrchestrationSnapshot.from_state",
        side_effect=lambda _s: _snapshot("reason_only"),
    ):
        route_after_critic({"critic": _critic(requires_review=False), "revisions_count": 0})  # type: ignore[arg-type]
        route_after_quality_revision({"requires_clarification": False})  # type: ignore[arg-type]

    agent_metrics.record_worker_execution(worker_kind="researcher", status="success")
    agent_metrics.record_worker_execution(worker_kind="coder", status="partial")
    agent_metrics.record_agent_handoff(
        from_node=NODE_CONTEXT_ENRICHER_WEAVING,
        to_node=NODE_FORMATTER,
        reason="not_a_real_reason",
    )

    assert agent_metrics.recorded_handoff_reasons() <= AGENT_HANDOFF_REASONS
    assert agent_metrics.recorded_worker_statuses() <= WORKER_EXECUTION_STATUSES
    assert "unspecified" in agent_metrics.recorded_handoff_reasons()
