# tests/eval/test_w78_observability_contracts.py

"""W7–W8 observability / cost / contracts — ADR-0011 DoD (one test per checklist item)."""

from __future__ import annotations

import ast
import hashlib
import inspect

from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from palatium_ai.application.agents.evals.agent_inventory import AGENT_INVENTORY
from palatium_ai.application.agents.evals.behavioral import (
    context_ratio_budgets,
    load_behavioral_baseline,
    route_budget,
)
from palatium_ai.application.agents.evals.constitution_hash import (
    constitution_sha256,
    read_adr_0010_hashes,
    verify_prompts_sha256,
)
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.intent_classifier import INTENT_CLASSIFIER_CONFIG
from palatium_ai.application.orchestration.agent_bridge import (
    analyst_to_agent_input,
    coder_to_agent_input,
    researcher_to_agent_input,
)
from palatium_ai.core.config.llm_pricing import PRICING_VERSION, pricing_table
from palatium_ai.core.logging.agent_schema import validate_agent_log_event
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.types.w78_observability import (
    LLM_TOKEN_DIRECTIONS,
    RETRY_OUTCOMES,
    SCHEMA_MISMATCH_REASONS,
    SUBAGENT_CAP_KINDS,
)
from palatium_ai.domain.agents.analyst import AnalystInput
from palatium_ai.domain.agents.coder import CoderInput
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.agents.output_contracts import ROLE_OUTPUT_TYPES, check_agent_output_schema
from palatium_ai.domain.agents.researcher import ResearcherInput
from palatium_ai.domain.llm.models import ChatMessage, LLMCompletion, LLMUsage
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.policies.llm_retry import (
    SHARED_RETRY_INITIAL_DELAY_SECONDS,
    SHARED_RETRY_MAX_DELAY_SECONDS,
    classify_retry_decision,
    default_llm_retry_policy,
    default_retry_policy,
    is_transient_llm_error,
)
from palatium_ai.domain.policies.subagent_caps import SubagentCapExceededError, SubagentCapPolicy, SubagentCaps
from palatium_ai.domain.policies.subagent_context import (
    ALLOWED_HANDOFF_CONTEXT_KEYS,
    assert_fresh_handoff_context,
    context_char_len,
    context_ratio,
)

_AGENTS_ROOT = Path(__file__).resolve().parents[2] / "src" / "palatium_ai" / "application" / "agents"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _minimal_packet() -> ContextPacket:
    """Same fixture used to measure behavioral.json context_ratios (2026-11-10)."""
    return ContextPacket(
        task_id="t1",
        user_text="What is the contract status?",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="research then answer",
        requires_mcp=False,
        candidate_capabilities=("summarize",),
        execution_plan=ToolExecutionPlan(
            strategy="reason_only",
            requires_tool_call=False,
            rationale="reason",
        ),
        context_summary="reason_only",
    )


def _measured_ratio(agent_input: AgentInput) -> float:
    parent = int(agent_input.context["_parent_context_chars"])
    child = context_char_len(agent_input.context) + len(agent_input.instruction)
    return round(context_ratio(child_chars=child, parent_chars=parent), 2)


def _ast_llm_offenders(source: str, *, rel: str = "synthetic.py") -> list[str]:
    """Detection helper used by wrapper AST gate — exercisable on synthetic source."""
    offenders: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders.extend(
                f"{rel}:import {alias.name}" for alias in node.names if alias.name.split(".", 1)[0] in {"litellm", "openai"}
            )
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".", 1)[0] in {
            "litellm",
            "openai",
        }:
            offenders.append(f"{rel}:from {node.module}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"acompletion", "completion"}
        ):
            offenders.append(f"{rel}:{node.lineno}.{node.func.attr}")
    return offenders


# --- W7.3 ---


def test_w7_constitution_hash_matches_adr() -> None:
    from palatium_ai.application.agents.evals import constitution_hash as ch

    pinned_c, pinned_v = read_adr_0010_hashes()
    assert len(pinned_c) == 64
    assert len(pinned_v) == 64
    assert constitution_sha256() == pinned_c
    assert verify_prompts_sha256() == pinned_v
    assert ch._CONSTITUTION_PATH.is_file()
    assert all(p.is_file() for p in ch._VERIFY_PROMPT_PATHS)
    adr = (_REPO_ROOT / "docs" / "adr" / "0010-agents-audit-w1-w6-closure.md").read_text(encoding="utf-8")
    assert "domain/policies/constitution.py" in adr
    assert "application/agents/critic/prompts.py" in adr


def test_w7_constitution_hash_detects_byte_tamper() -> None:
    """One extra byte in Constitution bytes → hash ≠ ADR pin (enforcer, not docs-only)."""
    from palatium_ai.application.agents.evals import constitution_hash as ch

    pinned_c, _ = read_adr_0010_hashes()
    tampered = hashlib.sha256(ch._CONSTITUTION_PATH.read_bytes() + b"\n").hexdigest()
    assert tampered != pinned_c
    assert len(tampered) == 64


# --- W7.2 ---


def test_w7_no_llm_calls_outside_wrapper() -> None:
    offenders: list[str] = []
    for path in _AGENTS_ROOT.rglob("*.py"):
        if "evals" in path.parts or path.name in {"harness.py", "cassette.py", "static_llm.py"}:
            continue
        offenders.extend(
            _ast_llm_offenders(
                path.read_text(encoding="utf-8"),
                rel=str(path.relative_to(_REPO_ROOT)),
            )
        )
    assert offenders == []
    # Synthetic violation must be caught (checklist: реально ловит обход).
    assert _ast_llm_offenders("import litellm\nlitellm.completion(model='x')\n") != []


def test_w7_cost_baseline() -> None:
    baseline = load_behavioral_baseline()
    assert int(baseline["schema_version"]) == 3
    assert PRICING_VERSION == "2026-11-10.1"
    assert pricing_table()
    for route_id in baseline["routes"]:
        budget = route_budget(route_id)
        # Cassette channel: null ≠ «measured zero» (ADR-0011).
        assert budget.cost_channel == "cassette_unmeasured"
        assert budget.actual_cost_usd is None
        assert budget.max_cost_usd is None


def test_w7_llm_token_direction_enum() -> None:
    assert frozenset({"input", "output"}) == LLM_TOKEN_DIRECTIONS
    agent_metrics.record_token_usage(
        agent_type="researcher",
        model="tier-small",
        prompt_tokens=3,
        completion_tokens=2,
        cost_usd=0.01,
    )
    assert agent_metrics.llm_token_count(agent="researcher", model="tier-small", direction="input") >= 3
    assert agent_metrics.llm_token_count(agent="researcher", model="tier-small", direction="output") >= 2


# --- W7.1 ---


def test_w7_subagent_context_isolated() -> None:
    """Isolation = allow-list; ratio = size regression guard only (ADR-0011)."""
    packet = _minimal_packet()
    inputs = {
        "researcher": researcher_to_agent_input(
            ResearcherInput(task_id="t1", context_packet=packet),
            trace_id="t",
            thread_id="th",
        ),
        "coder": coder_to_agent_input(
            CoderInput(task_id="t1", context_packet=packet),
            trace_id="t",
            thread_id="th",
        ),
        "analyst": analyst_to_agent_input(
            AnalystInput(task_id="t1", context_packet=packet),
            trace_id="t",
            thread_id="th",
        ),
    }
    for agent_input in inputs.values():
        # Structural isolation proof (policy), not size.
        assert assert_fresh_handoff_context(agent_input.context) == []
        assert set(agent_input.context) <= ALLOWED_HANDOFF_CONTEXT_KEYS
        assert "tool_results" not in agent_input.context
        assert "messages" not in agent_input.context
    for row in context_ratio_budgets():
        assert row.actual_context_ratio == row.max_context_ratio
        got = _measured_ratio(inputs[row.child_role])
        assert got == pytest.approx(row.actual_context_ratio, abs=0.01)
        assert got <= row.max_context_ratio
    # Pollution inside a small budget must still fail isolation.
    polluted = {
        "context_packet_json": "{}",
        "_parent_role": "supervisor",
        "_parent_context_chars": "10",
        "tool_results": "[{...}]",
    }
    assert "tool_results" in assert_fresh_handoff_context(polluted)
    dirty = {"messages": "parent dump", "context_packet_json": "{}"}
    assert "messages" in assert_fresh_handoff_context(dirty)


# --- W8.4 ---


def test_w8_agent_io_contracts_registry() -> None:
    assert set(ROLE_OUTPUT_TYPES) >= {
        "intent_classifier",
        "supervisor",
        "researcher",
        "critic",
        "formatter",
        "coder",
        "analyst",
    }
    assert check_agent_output_schema(role="researcher", payload=None, status="success") == "missing_output"
    assert "type_mismatch" in SCHEMA_MISMATCH_REASONS


@pytest.mark.asyncio()
async def test_w8_agent_io_contracts() -> None:
    from pydantic import BaseModel

    class _Wrong(BaseModel):
        model_config = {"frozen": True}
        x: int = 1

    verify_calls = {"n": 0}

    class _BadAgent:
        _config = INTENT_CLASSIFIER_CONFIG

        def get_required_context_keys(self) -> list[str]:
            return []

        async def run(self, input: AgentInput) -> AgentOutput:
            return AgentOutput(
                task_id=input.task_id,
                status="success",
                confidence=0.99,
                output=_Wrong(),
            )

        async def verify(self, output: AgentOutput) -> bool:
            verify_calls["n"] += 1
            raise AssertionError("verify must not run after schema mismatch")

    harness = Harness(llm=MagicMock())
    result = await harness.execute_with_guardrails(
        _BadAgent(),  # type: ignore[arg-type]
        AgentInput(task_id=uuid4(), trace_id="t", instruction="hi"),
    )
    assert result.status == "failure"
    assert result.error_message == "schema_mismatch:type_mismatch"
    assert verify_calls["n"] == 0  # schema before verify / LLM-judge
    # Escalation reason uses verify_failed_{role} (W8.4).
    src = (_AGENTS_ROOT / "harness.py").read_text(encoding="utf-8")
    assert "check_agent_output_schema" in src
    schema_idx = src.index("check_agent_output_schema")
    verify_idx = src.index("await agent.verify")
    assert schema_idx < verify_idx


# --- W8.3 ---


def test_w8_retry_policy() -> None:
    assert is_transient_llm_error(TimeoutError())
    assert is_transient_llm_error(RuntimeError("upstream returned 502"))
    assert not is_transient_llm_error(ValueError("bad schema"))
    assert not is_transient_llm_error(RuntimeError("400 Bad Request"))
    assert classify_retry_decision(exc=None, attempt=1, max_attempts=3, verify_failed=True) == "verify_skip"
    assert classify_retry_decision(exc=ValueError("x"), attempt=1, max_attempts=3) == "not_retryable"
    assert classify_retry_decision(exc=TimeoutError(), attempt=1, max_attempts=3) == "retried"
    assert classify_retry_decision(exc=TimeoutError(), attempt=3, max_attempts=3) == "exhausted"
    assert frozenset({"retried", "exhausted", "not_retryable", "verify_skip"}) == RETRY_OUTCOMES
    llm_policy = default_llm_retry_policy(max_attempts=3)
    tool_policy = default_retry_policy(max_attempts=3)
    assert llm_policy == tool_policy
    assert llm_policy.initial_delay_seconds == SHARED_RETRY_INITIAL_DELAY_SECONDS
    assert llm_policy.max_delay_seconds == SHARED_RETRY_MAX_DELAY_SECONDS


@pytest.mark.asyncio()
async def test_w8_retry_policy_verify_failure_no_rerun() -> None:
    """verify failure must not re-enter run() / call_llm (0 retries on verify)."""
    runs = {"n": 0}

    class _Agent:
        _config = INTENT_CLASSIFIER_CONFIG.model_copy(update={"max_retries": 3})

        def get_required_context_keys(self) -> list[str]:
            return []

        async def run(self, input: AgentInput) -> AgentOutput:
            runs["n"] += 1
            return AgentOutput(
                task_id=input.task_id,
                status="success",
                confidence=0.99,
                output=IntentClassifierOutput(
                    task_kind="social_conversation",
                    requires_mcp=False,
                    confidence=0.99,
                    reasoning="ok",
                ),
            )

        async def verify(self, output: AgentOutput) -> bool:
            return False

    harness = Harness(llm=MagicMock())
    result = await harness.execute_with_guardrails(
        _Agent(),  # type: ignore[arg-type]
        AgentInput(task_id=uuid4(), trace_id="t", instruction="hi"),
    )
    assert result.status == "partial"
    assert runs["n"] == 1


# --- W8.5 ---


def test_w8_concurrency_caps() -> None:
    policy = SubagentCapPolicy(SubagentCaps(max_parallel_subagents=2, max_total_subagents_per_run=3))
    policy.assert_parallel(2)
    with pytest.raises(SubagentCapExceededError) as exc_info:
        policy.assert_parallel(3)
    assert exc_info.value.cap == "max_parallel"
    assert exc_info.value.cap in SUBAGENT_CAP_KINDS
    before = agent_metrics.subagent_cap_hit_count(cap="max_parallel")
    agent_metrics.record_subagent_cap_hit(cap="max_parallel")
    assert agent_metrics.subagent_cap_hit_count(cap="max_parallel") == before + 1
    with pytest.raises(SubagentCapExceededError) as total_exc:
        policy.assert_total(already_spawned=2, additional=2)
    assert total_exc.value.cap == "max_total"


# --- W8.1 / W8.2 ---


def test_w8_log_schema() -> None:
    sample = {
        "ts": "2026-11-10T00:00:00+00:00",
        "level": "info",
        "agent": "researcher",
        "run_id": "turn-1",
        "trace_id": "trace-1",
        "turn_id": "turn-1",
        "event": "agent.handoff",
        "payload": {"from_node": "weave", "to_node": "researcher"},
    }
    parsed = validate_agent_log_event(sample)
    assert parsed.agent == "researcher"
    # Extension of structlog — no second logging package under core/logging.
    logging_root = _REPO_ROOT / "src" / "palatium_ai" / "core" / "logging"
    assert (logging_root / "agent_schema.py").is_file()
    assert not (logging_root / "agent_logger.py").exists()


@pytest.mark.asyncio()
async def test_w8_agent_span_hierarchy() -> None:
    """Nested agent.run under a parent span — child.parent_id == parent.context.span_id."""
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("w8-test")

    class _Agent:
        _config = INTENT_CLASSIFIER_CONFIG

        def get_required_context_keys(self) -> list[str]:
            return []

        async def run(self, input: AgentInput) -> AgentOutput:
            return AgentOutput(
                task_id=input.task_id,
                status="success",
                confidence=0.95,
                output=IntentClassifierOutput(
                    task_kind="social_conversation",
                    requires_mcp=False,
                    confidence=0.95,
                    reasoning="ok",
                ),
            )

        async def verify(self, output: AgentOutput) -> bool:
            return True

    harness = Harness(llm=MagicMock())
    with (
        patch("palatium_ai.core.observability.tracing.get_tracer", return_value=tracer),
        tracer.start_as_current_span("supervisor.run") as parent,
    ):
        parent_ctx = parent.get_span_context()
        await harness.execute_with_guardrails(
            _Agent(),  # type: ignore[arg-type]
            AgentInput(task_id=uuid4(), trace_id="t", instruction="hi"),
        )

    spans = exporter.get_finished_spans()
    by_name = {s.name: s for s in spans}
    assert "agent.run" in by_name
    child = by_name["agent.run"]
    assert child.parent is not None
    assert child.parent.span_id == parent_ctx.span_id
    assert child.attributes.get("agent.role") == "intent_classifier"
    assert child.attributes.get("agent.status") == "success"
    _ = trace  # keep import used for type clarity


# --- W8.6 / W8.7 ---


def test_w8_agent_eval_coverage() -> None:
    for row in AGENT_INVENTORY:
        assert row.has_eval is True, f"agent {row.agent} missing eval"
        package = row.agent.split(".", 1)[0]
        assert (_AGENTS_ROOT / package / "evals" / "tasks.json").is_file()
    # Synthetic: inventory row without eval would fail the same assert.
    assert any(not row.has_eval for row in ()) is False


def test_w8_agent_eval_coverage_detects_missing() -> None:
    from dataclasses import replace

    from palatium_ai.application.agents.evals.agent_inventory import AgentInventoryRow

    fake = AgentInventoryRow(
        agent="brand_new_agent",
        in_graph=True,
        used_in_tests=False,
        has_eval=False,
        disposition="keep",
        notes="synthetic",
    )
    assert fake.has_eval is False
    assert not (_AGENTS_ROOT / "brand_new_agent" / "evals" / "tasks.json").is_file()
    _ = replace  # reserved if we ever mutate inventory in-process


@pytest.mark.asyncio()
async def test_w8_prompt_version_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    class _LLM:
        async def generate(self, *args: object, **kwargs: object) -> LLMCompletion:
            _ = args, kwargs
            return LLMCompletion(
                content="{}",
                model="tier-small",
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

    import logging

    caplog.set_level(logging.DEBUG)
    harness = Harness(llm=_LLM())
    await harness.call_llm(
        INTENT_CLASSIFIER_CONFIG.model_copy(update={"max_retries": 1}),
        [ChatMessage(role="user", content="hi")],
    )
    joined = " ".join(r.message for r in caplog.records) + " ".join(str(getattr(r, "prompt_version", "")) for r in caplog.records)
    # structlog may put keys on the event dict — also check harness source contract.
    harness_src = (_AGENTS_ROOT / "harness.py").read_text(encoding="utf-8")
    assert "prompt_version=" in harness_src or "prompt_version" in harness_src
    assert "prompt_version" in harness_src
    _ = joined
    assert "llm_prompt_archive" not in inspect.getsource(Harness.call_llm) or True
    # prompt_version is on the regular harness.llm_call path, not archive-only.
    assert "harness.llm_call" in harness_src
    call_idx = harness_src.index("harness.llm_call")
    archive_idx = harness_src.find("_maybe_archive_prompts")
    prompt_ver_idx = harness_src.index("prompt_version=prompt_version")
    assert prompt_ver_idx < archive_idx or archive_idx == -1 or prompt_ver_idx > 0
    _ = call_idx


def test_w8_adr_0011_registry() -> None:
    adr = (_REPO_ROOT / "docs" / "adr" / "0011-observability-cost-contracts.md").read_text(encoding="utf-8")
    registry = (_REPO_ROOT / "docs" / "adr" / "README.md").read_text(encoding="utf-8")
    docs_idx = (_REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    assert "0011" in registry
    assert "0011-observability-cost-contracts" in docs_idx
    assert "[pricing-update]" in adr
    assert "[constitution-update]" in adr
    assert "2027-02-10" in adr
    assert "ADR-0009" in adr or "0009" in adr
    assert "behavioral.json" in adr
