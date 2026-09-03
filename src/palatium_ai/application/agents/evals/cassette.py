# src/palatium_ai/application/agents/evals/cassette.py

"""Cassette LLM fixtures — deterministic agent evals without live providers (075)."""

from __future__ import annotations

import json

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from palatium_ai.application.agents.context_enricher import CONTEXTUALIZER_CONFIG, ContextualizerAgent
from palatium_ai.application.agents.critic import CRITIC_CONFIG, CriticAgent
from palatium_ai.application.agents.evals.static_llm import SequentialStaticLLMPort, StaticLLMPort
from palatium_ai.application.agents.formatter import FORMATTER_CONFIG, FormatterAgent
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.intent_classifier import INTENT_CLASSIFIER_CONFIG, IntentClassifierAgent
from palatium_ai.application.agents.memory_keeper import MEMORY_KEEPER_CONFIG, MemoryKeeperAgent
from palatium_ai.application.agents.researcher import RESEARCHER_CONFIG, ResearcherAgent
from palatium_ai.application.agents.supervisor import SUPERVISOR_CONFIG, SupervisorAgent
from palatium_ai.application.agents.text_ingestor import TEXT_INGESTOR_CONFIG, TextIngestorAgent
from palatium_ai.application.agents.text_ingestor.parsing import text_ingestor_output_to_dict
from palatium_ai.application.orchestration.agent_bridge import (
    contextualizer_output_to_task_result,
    contextualizer_to_agent_input,
    critic_output_to_task_result,
    critic_to_agent_input,
    formatter_output_to_task_result,
    formatter_to_agent_input,
    intent_output_to_task_result,
    intent_to_agent_input,
    memory_keeper_output_to_task_result,
    memory_keeper_to_agent_input,
    researcher_output_to_task_result,
    researcher_to_agent_input,
    supervisor_output_to_task_result,
    supervisor_to_agent_input,
)
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.critic import CriticInput
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.agents.intent import IntentClassifierInput, TaskKind
from palatium_ai.domain.agents.memory_keeper import MemoryKeeperInput
from palatium_ai.domain.agents.messages import AgentInput
from palatium_ai.domain.agents.researcher import ResearcherInput
from palatium_ai.domain.agents.supervisor import SupervisorInput, WorkerRoute
from palatium_ai.domain.agents.text_ingestor import TextIngestorOutput
from palatium_ai.domain.mcp.models import (
    MCPToolCall,
    MCPToolDescriptor,
    MCPToolResult,
    MCPToolSummary,
    ToolExecutionPlan,
)
from palatium_ai.domain.mcp.platform_schemas import (
    PLATFORM_GRAPH_QUERY_SCHEMA,
    PLATFORM_SEARCH_KNOWLEDGE_SCHEMA,
    PLATFORM_SEARCH_MEMORY_SCHEMA,
    PLATFORM_WEB_FALLBACK_SCHEMA,
)
from palatium_ai.domain.memory.budget import MemoryPromptBudget
from palatium_ai.domain.memory.contextualizer import ContextualizerInput
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.domain.policies.types import ExecutionStrategy

_CASSETTE_ROOT = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "llm"

CassetteRunner = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _task_id(task: dict[str, Any]) -> str:
    raw = task.get("id") or task.get("task_id")
    return str(raw) if raw else "cassette-task"


def load_cassette_response(relative_path: str) -> str:
    """Load recorded LLM response from tests/fixtures/llm/."""
    path = _CASSETTE_ROOT / relative_path
    if not path.is_file():
        msg = f"cassette not found: {relative_path}"
        raise FileNotFoundError(msg)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("response"), str):
        return cast("str", payload["response"])
    if isinstance(payload, str):
        return payload
    msg = f'cassette {relative_path} must be a string or {{"response": ...}}'
    raise ValueError(msg)


def _require_cassette(task: dict[str, Any]) -> str:
    cassette = task.get("cassette")
    if not isinstance(cassette, str) or not cassette.strip():
        msg = "cassette task requires cassette path"
        raise ValueError(msg)
    return cassette.strip()


def _dialog_from_input(raw_input: dict[str, Any], *, thread_id: str) -> DialogTurnWindow:
    dialog = raw_input.get("dialog", [])
    if not isinstance(dialog, list):
        msg = "dialog must be a list of turns"
        raise ValueError(msg)
    turns: list[DialogTurn] = []
    for idx, turn in enumerate(dialog):
        if not isinstance(turn, dict):
            continue
        role = turn.get("role")
        content = turn.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        turns.append(
            DialogTurn(
                id=uuid4(),
                thread_id=thread_id,
                role=role,
                content=content,
                seq=idx,
                created_at=datetime.now(UTC),
            )
        )
    return DialogTurnWindow(thread_id=thread_id, turns=tuple(turns))


def _packet_from_raw(raw: dict[str, Any], task_id: str) -> ContextPacket:
    strategy = str(raw.get("selected_strategy", "reason_only"))
    return ContextPacket(
        task_id=task_id,
        user_text=str(raw.get("user_text", "eval")),
        task_kind=cast("TaskKind", raw.get("task_kind", "knowledge_request")),
        route=cast("WorkerRoute", raw.get("route", "formatter")),
        route_plan=str(raw.get("route_plan", "cassette eval")),
        requires_mcp=bool(raw.get("requires_mcp", False)),
        candidate_capabilities=tuple(raw.get("candidate_capabilities", ())),
        execution_plan=ToolExecutionPlan(
            strategy=cast("ExecutionStrategy", strategy),
            requires_tool_call=bool(raw.get("requires_tool_call", False)),
            server_name=raw.get("server_name"),
            tool_name=raw.get("tool_name"),
            rationale=str(raw.get("rationale", "cassette eval")),
        ),
        context_summary=str(raw.get("context_summary", "cassette eval")),
        local_retrieval_empty=bool(raw.get("local_retrieval_empty", False)),
    )


def _reason_only_packet(task_id: str, user_text: str, *, task_kind: str = "knowledge_request") -> ContextPacket:
    return ContextPacket(
        task_id=task_id,
        user_text=user_text,
        task_kind=cast("TaskKind", task_kind),
        route="researcher",
        route_plan="Summarize from context",
        requires_mcp=False,
        candidate_capabilities=(),
        execution_plan=ToolExecutionPlan(
            strategy="reason_only",
            requires_tool_call=False,
            rationale="cassette eval",
        ),
        context_summary="cassette eval",
    )


class _ResearcherEvalMcpRegistry:
    """Minimal platform MCP registry for researcher cassette evals."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, MCPToolCall]] = []
        self._tools = {
            "platform": [
                MCPToolDescriptor(
                    name="search_knowledge",
                    description="Hybrid search over ingested knowledge chunks indexed for retrieval.",
                    input_schema=PLATFORM_SEARCH_KNOWLEDGE_SCHEMA,
                    annotations={"readOnlyHint": True},
                ),
                MCPToolDescriptor(
                    name="search_memory",
                    description="Hybrid search episodic memory entries for user thread context.",
                    input_schema=PLATFORM_SEARCH_MEMORY_SCHEMA,
                    annotations={"readOnlyHint": True},
                ),
                MCPToolDescriptor(
                    name="graph_query",
                    description="Read-only parameterized Cypher query against the long-term knowledge graph.",
                    input_schema=PLATFORM_GRAPH_QUERY_SCHEMA,
                    annotations={"readOnlyHint": True},
                ),
                MCPToolDescriptor(
                    name="web_fallback",
                    description="External web search after local knowledge and memory retrieval returned empty.",
                    input_schema=PLATFORM_WEB_FALLBACK_SCHEMA,
                    annotations={"readOnlyHint": True},
                ),
            ]
        }

    def list_servers(self) -> list[str]:
        return list(self._tools)

    async def list_tools(self, server_name: str) -> list[MCPToolDescriptor]:
        return self._tools.get(server_name, [])

    async def list_tool_summaries(self, server_name: str) -> list[MCPToolSummary]:
        tools = await self.list_tools(server_name)
        return [tool.to_summary() for tool in tools]

    async def get_tool(self, server_name: str, tool_name: str) -> MCPToolDescriptor | None:
        tools = await self.list_tools(server_name)
        return next((tool for tool in tools if tool.name == tool_name), None)

    async def call_tool(self, server_name: str, tool_call: MCPToolCall) -> MCPToolResult:
        self.calls.append((server_name, tool_call))
        query = str(tool_call.arguments.get("query", ""))
        if tool_call.name == "graph_query":
            payload = {
                "tool": tool_call.name,
                "row_count": 1,
                "rows": [{"fact": f"Cassette graph row for {query or 'graph'}"}],
            }
        elif tool_call.name == "web_fallback":
            payload = {
                "tool": tool_call.name,
                "query": query,
                "hits": [{"title": f"Web hit for {query}", "score": 0.72, "source": "cassette"}],
                "hit_count": 1,
                "source": "web",
                "reliability": "external",
            }
        else:
            payload = {
                "tool": tool_call.name,
                "query": query,
                "hits": [{"text": f"Cassette hit for {query}", "score": 0.88}],
                "hit_count": 1,
            }
        return MCPToolResult(
            content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            is_error=False,
        )


async def run_intent_classifier_cassette(task: dict[str, Any]) -> dict[str, Any]:
    cassette = _require_cassette(task)
    llm_response = load_cassette_response(cassette)
    raw_input = task.get("input")
    if not isinstance(raw_input, dict):
        msg = "intent cassette task requires input object"
        raise ValueError(msg)

    task_input = IntentClassifierInput(
        task_id=_task_id(task),
        text=str(raw_input.get("text", "")),
        continuation_kind=raw_input.get("continuation_kind"),
        has_prior_dialog=bool(raw_input.get("has_prior_dialog", False)),
    )
    llm = StaticLLMPort(llm_response)
    harness = Harness(llm=llm)
    agent = IntentClassifierAgent(harness, INTENT_CLASSIFIER_CONFIG)
    agent_input = intent_to_agent_input(task_input, trace_id="eval-cassette", thread_id="eval-cassette")
    output = await harness.execute_with_guardrails(agent, agent_input)
    result = intent_output_to_task_result(output, task_id=task_input.task_id, agent_role=agent.config.role)
    if result.output is None:
        return {"status": result.status, "error": result.error}
    return {
        "task_kind": result.output.task_kind,
        "requires_mcp": result.output.requires_mcp,
        "status": result.status,
        "confidence": result.confidence,
    }


async def run_context_enricher_cassette(task: dict[str, Any]) -> dict[str, Any]:
    cassette = _require_cassette(task)
    llm_response = load_cassette_response(cassette)
    raw_input = task.get("input")
    if not isinstance(raw_input, dict):
        raw_input = {
            "user_text": task.get("user_text", ""),
            "dialog": task.get("dialog", []),
        }
    thread_id = "eval-cassette"
    task_input = ContextualizerInput(
        task_id=_task_id(task),
        user_text=str(raw_input.get("user_text", task.get("user_text", ""))),
        dialog_window=_dialog_from_input(raw_input, thread_id=thread_id),
        memory_hints=(),
        prompt_budget=MemoryPromptBudget(),
        task_kind=None,
        requires_mcp=False,
    )
    llm = StaticLLMPort(llm_response)
    harness = Harness(llm=llm)
    agent = ContextualizerAgent(harness, CONTEXTUALIZER_CONFIG)
    agent_input = contextualizer_to_agent_input(task_input, trace_id="eval-cassette", thread_id=thread_id)
    output = await harness.execute_with_guardrails(agent, agent_input)
    result = contextualizer_output_to_task_result(
        output,
        task_id=task_input.task_id,
        agent_role=agent.config.role,
    )
    if result.output is None:
        return {"status": result.status, "error": result.error}
    return {
        "continuation_kind": result.output.continuation_kind,
        "refers_to_prior": result.output.refers_to_prior,
        "status": result.status,
        "confidence": result.output.confidence,
    }


async def run_researcher_cassette(task: dict[str, Any]) -> dict[str, Any]:
    raw_input = task.get("input")
    if not isinstance(raw_input, dict):
        msg = "researcher cassette task requires input object"
        raise ValueError(msg)
    task_id = _task_id(task)
    requires_mcp = bool(raw_input.get("requires_mcp", False))
    requires_tool_call = bool(raw_input.get("requires_tool_call", False))
    if requires_mcp or requires_tool_call:
        packet = _packet_from_raw(raw_input, task_id)
    else:
        user_text = str(raw_input.get("user_text", raw_input.get("input", "")))
        task_kind = str(raw_input.get("task_kind", "knowledge_request"))
        packet = _reason_only_packet(task_id, user_text, task_kind=task_kind)

    args_cassette = task.get("args_cassette")
    if isinstance(args_cassette, str) and args_cassette.strip():
        llm: StaticLLMPort | SequentialStaticLLMPort = SequentialStaticLLMPort(
            [load_cassette_response(args_cassette.strip())]
        )
    else:
        cassette = _require_cassette(task)
        llm = StaticLLMPort(load_cassette_response(cassette))

    mcp_registry = _ResearcherEvalMcpRegistry() if requires_mcp or requires_tool_call else None
    task_input = ResearcherInput(task_id=task_id, context_packet=packet)
    harness = Harness(llm=llm)
    agent = ResearcherAgent(harness, RESEARCHER_CONFIG, llm, mcp_registry=mcp_registry)
    agent_input = researcher_to_agent_input(
        task_input,
        trace_id="eval-cassette",
        thread_id="eval-cassette",
        user_id="eval-user",
        org_id="eval-org",
    )
    output = await harness.execute_with_guardrails(agent, agent_input)
    result = researcher_output_to_task_result(output, task_id=task_id, agent_role=agent.config.role)
    sources = result.output.sources_used if result.output is not None else ()
    summary = result.output.summary if result.output is not None else ""
    return {
        "status": result.status,
        "requires_mcp": requires_mcp,
        "confidence": result.confidence,
        "has_summary": bool(summary.strip()),
        "summary": summary,
        "sources_used": list(sources),
        "mcp_tool": raw_input.get("tool_name") if requires_tool_call else None,
        "used_mcp_source": any(source.startswith("mcp:platform.") for source in sources),
    }


async def run_memory_keeper_cassette(task: dict[str, Any]) -> dict[str, Any]:
    cassette = _require_cassette(task)
    llm_response = load_cassette_response(cassette)
    transcript = task.get("transcript")
    if not isinstance(transcript, str) or not transcript.strip():
        msg = "memory_keeper cassette task requires transcript"
        raise ValueError(msg)
    task_id = _task_id(task)
    task_input = MemoryKeeperInput(
        task_id=task_id,
        thread_id="eval-cassette",
        transcript_excerpt=transcript,
        existing_memory_texts=(),
    )
    llm = StaticLLMPort(llm_response)
    harness = Harness(llm=llm)
    agent = MemoryKeeperAgent(harness, MEMORY_KEEPER_CONFIG)
    agent_input = memory_keeper_to_agent_input(task_input, trace_id="eval-cassette", thread_id="eval-cassette")
    output = await harness.execute_with_guardrails(agent, agent_input)
    result = memory_keeper_output_to_task_result(output, task_id=task_id, agent_role=agent.config.role)
    facts: list[dict[str, object]] = []
    if result.output is not None:
        facts = [{"text": fact.text, "kind": fact.kind, "confidence": fact.confidence} for fact in result.output.facts]
    return {"status": result.status, "facts": facts}


async def run_supervisor_cassette(task: dict[str, Any]) -> dict[str, Any]:
    _require_cassette(task)
    task_id = _task_id(task)
    caps = task.get("candidate_capabilities", ())
    task_input = SupervisorInput(
        task_id=task_id,
        user_text=str(task.get("user_text", "")),
        task_kind=cast("TaskKind", task.get("task_kind")),
        requires_mcp=bool(task.get("requires_mcp", False)),
        candidate_capabilities=tuple(caps) if isinstance(caps, (list, tuple)) else (),
        classification_confidence=float(task.get("classification_confidence", 0.0)),
    )
    llm = StaticLLMPort("{}")
    harness = Harness(llm=llm)
    agent = SupervisorAgent(harness, SUPERVISOR_CONFIG)
    agent_input = supervisor_to_agent_input(task_input, trace_id="eval-cassette", thread_id="eval-cassette")
    output = await harness.execute_with_guardrails(agent, agent_input)
    result = supervisor_output_to_task_result(output, task_id=task_id, agent_role=agent.config.role)
    if result.output is None:
        return {"status": result.status, "error": result.error}
    return {
        "status": result.status,
        "route": result.output.route,
        "target_agent": result.output.target_agent,
        "confidence": result.confidence,
    }


def _critic_input_from_task(task: dict[str, Any]) -> CriticInput:
    raw_input = task.get("input")
    if not isinstance(raw_input, dict):
        msg = "critic cassette task requires input object"
        raise ValueError(msg)
    task_id = _task_id(task)
    worker_summary = raw_input.get("worker_summary")
    return CriticInput(
        task_id=task_id,
        context_packet=_packet_from_raw(raw_input, task_id),
        classification_confidence=float(raw_input.get("classification_confidence", 0.0)),
        classification_reasoning=str(raw_input.get("classification_reasoning", "cassette eval")),
        worker_summary=worker_summary if isinstance(worker_summary, str) else None,
        selected_strategy=cast("ExecutionStrategy", raw_input.get("selected_strategy", "reason_only")),
        continuation_kind=raw_input.get("continuation_kind"),
        user_input_chars=int(raw_input.get("user_input_chars", 0)),
    )


async def run_critic_cassette(task: dict[str, Any]) -> dict[str, Any]:
    cassette = _require_cassette(task)
    llm_response = load_cassette_response(cassette)
    task_input = _critic_input_from_task(task)
    llm = StaticLLMPort(llm_response)
    harness = Harness(llm=llm)
    agent = CriticAgent(harness, CRITIC_CONFIG)
    agent_input = critic_to_agent_input(task_input, trace_id="eval-cassette", thread_id="eval-cassette")
    output = await harness.execute_with_guardrails(agent, agent_input)
    result = critic_output_to_task_result(output, task_id=task_input.task_id, agent_role=agent.config.role)
    resolved: dict[str, Any] = {
        "status": result.status,
        "requires_review": result.requires_review,
        "llm_invoked": len(llm.calls) > 0,
    }
    if result.output is not None:
        resolved["accuracy_score"] = result.output.accuracy_score
        resolved["safety_score"] = result.output.safety_score
    return resolved


async def run_formatter_cassette(task: dict[str, Any]) -> dict[str, Any]:
    cassette = _require_cassette(task)
    llm_response = load_cassette_response(cassette)
    raw_input = task.get("input")
    if not isinstance(raw_input, dict):
        msg = "formatter cassette task requires input object"
        raise ValueError(msg)
    task_id = _task_id(task)
    task_input = FormatterInput(
        task_id=task_id,
        context_packet=_packet_from_raw(raw_input, task_id),
        worker_summary=raw_input.get("worker_summary") if isinstance(raw_input.get("worker_summary"), str) else None,
        critic_summary=raw_input.get("critic_summary") if isinstance(raw_input.get("critic_summary"), str) else None,
        requires_review=bool(raw_input.get("requires_review", False)),
        requires_user_choice=bool(raw_input.get("requires_user_choice", False)),
        underspecification_kind=str(raw_input.get("underspecification_kind", "none")),
        revision_feedback=raw_input.get("revision_feedback")
        if isinstance(raw_input.get("revision_feedback"), str)
        else None,
    )
    llm = StaticLLMPort(llm_response)
    harness = Harness(llm=llm)
    agent = FormatterAgent(harness, FORMATTER_CONFIG)
    agent_input = formatter_to_agent_input(task_input, trace_id="eval-cassette", thread_id="eval-cassette")
    output = await harness.execute_with_guardrails(agent, agent_input)
    result = formatter_output_to_task_result(output, task_id=task_id, agent_role=agent.config.role)
    if result.output is None:
        return {"status": result.status, "error": result.error}
    return {
        "status": result.status,
        "schema_version": result.output.schema_version,
        "block_count": len(result.output.blocks),
        "title": result.output.title,
    }


async def run_text_ingestor_cassette(task: dict[str, Any]) -> dict[str, Any]:
    _require_cassette(task)
    raw_input = task.get("input")
    if not isinstance(raw_input, dict):
        msg = "text_ingestor cassette task requires input object"
        raise ValueError(msg)
    task_id = _task_id(task)
    context = {
        "task_id": str(raw_input.get("task_id", task_id)),
        "thread_id": str(raw_input.get("thread_id", "eval-cassette")),
        "raw_text": str(raw_input.get("raw_text", "")),
    }
    if raw_input.get("max_chunk_chars") is not None:
        context["max_chunk_chars"] = str(raw_input["max_chunk_chars"])
    if isinstance(raw_input.get("document_id"), str):
        context["document_id"] = raw_input["document_id"]
    if raw_input.get("enrich_context_prefix") is True:
        context["enrich_context_prefix"] = "true"
    if isinstance(raw_input.get("document_title"), str):
        context["document_title"] = raw_input["document_title"]

    cassette = task.get("cassette")
    llm_response = load_cassette_response(cassette) if isinstance(cassette, str) and cassette.strip() else "{}"
    harness = Harness(llm=StaticLLMPort(llm_response))
    agent = TextIngestorAgent(harness, TEXT_INGESTOR_CONFIG)
    agent_input = AgentInput(
        task_id=uuid4(),
        trace_id="eval-cassette",
        instruction="chunk document for ingest",
        context=context,
    )
    output = await harness.execute_with_guardrails(agent, agent_input)
    if not isinstance(output.output, TextIngestorOutput):
        return {"status": output.status, "error": output.error_message}
    return text_ingestor_output_to_dict(output.output, status=output.status)


CASSETTE_RUNNERS: dict[str, CassetteRunner] = {
    "intent_classifier": run_intent_classifier_cassette,
    "context_enricher": run_context_enricher_cassette,
    "researcher": run_researcher_cassette,
    "memory_keeper": run_memory_keeper_cassette,
    "supervisor": run_supervisor_cassette,
    "critic": run_critic_cassette,
    "formatter": run_formatter_cassette,
    "text_ingestor": run_text_ingestor_cassette,
}


async def run_cassette_task(agent: str, task: dict[str, Any]) -> dict[str, Any]:
    runner = CASSETTE_RUNNERS.get(agent)
    if runner is None:
        msg = f"no cassette runner for agent {agent}"
        raise ValueError(msg)
    return await runner(task)
