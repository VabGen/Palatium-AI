# src/palatium_ai/application/agents/researcher_agent.py

"""Агент Researcher — текстовый worker для поиска/анализа без side effects."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING, Literal, cast

from langgraph.types import interrupt

from palatium_ai.application.agents.base import BaseAgent
from palatium_ai.application.services.mcp_capabilities import MCPCapabilityIndex
from palatium_ai.application.services.tool_argument_builder import ToolArgumentBuilder
from palatium_ai.application.tools.executor import ToolExecutor
from palatium_ai.application.tools.mcp import (
    MCPToolCallOutcome,
    MCPToolCallParams,
    call_mcp_tool,
)
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.agents.researcher import (
    RESEARCHER_TOOL_ARGS_INVALID,
    ResearcherInput,
    ResearcherOutput,
    ResearcherTaskResult,
)
from palatium_ai.domain.llm.json_codec import loads_llm_json
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.domain.mcp.discovery_policy import McpDiscoveryPolicy
from palatium_ai.domain.mcp.tool_policy import (
    classify_risk_tier,
    classify_side_effect,
    requires_interrupt_before_call,
    resolve_platform_pin,
)
from palatium_ai.domain.memory.tool_output import compress_worker_context, wrap_untrusted_tool_output

if TYPE_CHECKING:
    from palatium_ai.application.services.cost_budget import CostBudgetService
    from palatium_ai.domain.agents.contracts import AgentContext
    from palatium_ai.domain.ports.llm import LLMPort
    from palatium_ai.infrastructure.database.repositories import McpToolCallRepository
    from palatium_ai.infrastructure.mcp.registry import MCPRegistry


RESEARCHER_CONFIG = AgentConfig(
    name="researcher",
    role="researcher",
    model_tier="mid",
    temperature=0.1,
    allowed_tools=(
        "mcp:edms.search_documents",
        "mcp:edms.archive_document",
        "mcp:analytics.get_sales_metrics",
    ),
    timeout_seconds=90,
    max_retries=3,
    confidence_threshold=0.7,
)

_SYSTEM_PROMPT = """You are a Researcher worker in a universal MCP-driven office assistant platform.
Given a user request, task kind, required capabilities, and a routing plan, provide a concise helpful result.
If prior_context is provided, treat it as source material for the ask.
When the current user message already contains a fuller payload than prior_context,
prefer the current message; do not claim missing context when either source has the answer.
If revision_feedback is provided, treat the previous answer as rejected and correct those issues.
Never invent MCP/tool results. If tools were required but not executed, say they are unavailable.

Return ONLY valid JSON:
{
  "summary": "<short answer or actionable research result>",
  "confidence": <0.0-1.0>,
  "sources_used": ["llm_internal_reasoning"]
}
"""


class ResearcherAgent(BaseAgent):
    """Исполняет platform-level research/orchestration-prep задачи."""

    config = RESEARCHER_CONFIG

    def __init__(
        self,
        llm: LLMPort,
        mcp_registry: MCPRegistry | None = None,
        *,
        mcp_tool_call_repository: McpToolCallRepository | None = None,
        capability_index: MCPCapabilityIndex | None = None,
        cost_budget: CostBudgetService | None = None,
    ) -> None:
        super().__init__(llm, cost_budget=cost_budget)
        self._mcp_registry = mcp_registry
        self._mcp_tool_call_repository = mcp_tool_call_repository
        self._tool_executor = ToolExecutor(self.config)
        self._capability_index: MCPCapabilityIndex | None
        if capability_index is not None:
            self._capability_index = capability_index
        elif mcp_registry is not None:
            self._capability_index = MCPCapabilityIndex(mcp_registry)
        else:
            self._capability_index = None
        self._argument_builder = ToolArgumentBuilder(llm)

    @traceable(name="researcher.execute")
    async def execute(
        self,
        task_input: ResearcherInput,
        context: AgentContext,
    ) -> ResearcherTaskResult:
        """Генерирует результат по route plan и применяет confidence gate."""
        _ = context
        agent_metrics.record_node_execution("researcher", "researcher_node")

        execution_plan = task_input.context_packet.execution_plan
        mcp_gate = McpDiscoveryPolicy.should_attempt_tool_execution(
            requires_mcp=task_input.context_packet.requires_mcp,
            requires_tool_call=execution_plan.requires_tool_call,
            selected_strategy=execution_plan.strategy,
        )
        if mcp_gate.allowed and self._mcp_registry is not None and self._capability_index is not None:
            mcp_result = await self._execute_mcp_capability(task_input, context)
            if mcp_result is not None:
                return mcp_result

        # Fail closed: never invent tool results when MCP was required or planned.
        if task_input.context_packet.requires_mcp or execution_plan.requires_tool_call:
            output = ResearcherOutput(
                summary="Required MCP capability is unavailable. No tool result was produced.",
                confidence=0.0,
                sources_used=(),
            )
            return ResearcherTaskResult(
                task_id=task_input.task_id,
                agent_role=self.config.role,
                status="failure",
                confidence=0.0,
                requires_review=True,
                output=output,
                error="MCP capability unavailable",
            )

        messages = [
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=json.dumps(
                    {
                        "user_text": task_input.context_packet.user_text,
                        "task_kind": task_input.context_packet.task_kind,
                        "requires_mcp": task_input.context_packet.requires_mcp,
                        "candidate_capabilities": task_input.context_packet.candidate_capabilities,
                        "route_plan": task_input.context_packet.route_plan,
                        "context_summary": task_input.context_packet.context_summary,
                        "prior_context": task_input.prior_context,
                        "revision_feedback": task_input.revision_feedback,
                    },
                    ensure_ascii=False,
                ),
            ),
        ]

        try:
            completion = await self._call_llm(messages, model=self.config.llm_model, response_format="json_object")
            output = _parse_researcher_output(completion.content)
        except Exception as exc:
            agent_metrics.record_error("researcher", type(exc).__name__)
            return ResearcherTaskResult(
                task_id=task_input.task_id,
                agent_role=self.config.role,
                status="failure",
                confidence=0.0,
                requires_review=True,
                output=None,
                error=str(exc),
            )

        requires_review = output.confidence < self.config.confidence_threshold
        status: Literal["success", "failure", "partial"] = "partial" if requires_review else "success"
        if requires_review:
            agent_metrics.record_human_escalation("low_confidence_research")

        return ResearcherTaskResult(
            task_id=task_input.task_id,
            agent_role=self.config.role,
            status=status,
            confidence=output.confidence,
            requires_review=requires_review,
            output=output,
        )

    async def _execute_mcp_capability(
        self,
        task_input: ResearcherInput,
        context: AgentContext,
    ) -> ResearcherTaskResult | None:
        """Пытается исполнить задачу через MCP capability index."""
        if self._mcp_registry is None or self._capability_index is None:
            return None
        mcp_registry = self._mcp_registry

        execution_plan = task_input.context_packet.execution_plan
        if execution_plan.requires_tool_call:
            server_name = execution_plan.server_name
            tool_name = execution_plan.tool_name
        else:
            binding = await self._capability_index.resolve_best(
                task_text=task_input.context_packet.user_text,
                requested_capabilities=task_input.context_packet.candidate_capabilities,
            )
            if binding is None:
                return None
            server_name = binding.server_name
            tool_name = binding.tool_name

        if server_name is None or tool_name is None:
            return None

        tools = await self._mcp_registry.list_tools(server_name)
        descriptor = next((tool for tool in tools if tool.name == tool_name), None)
        if descriptor is None:
            return None

        try:
            arguments = await self._argument_builder.build_arguments(
                descriptor=descriptor,
                user_text=task_input.context_packet.user_text,
                route_plan=task_input.context_packet.route_plan,
                task_kind=task_input.context_packet.task_kind,
                candidate_capabilities=task_input.context_packet.candidate_capabilities,
                conversation_id=context.thread_id,
            )
        except Exception as exc:
            _ = exc
            agent_metrics.record_error("researcher", type(exc).__name__)
            output = ResearcherOutput(
                summary=(
                    f"Could not build valid arguments for MCP tool "
                    f"{server_name}.{tool_name}. No tool call was executed."
                ),
                confidence=0.0,
                sources_used=(),
            )
            return ResearcherTaskResult(
                task_id=task_input.task_id,
                agent_role=self.config.role,
                status="failure",
                confidence=0.0,
                requires_review=True,
                output=output,
                error=RESEARCHER_TOOL_ARGS_INVALID,
            )

        params = MCPToolCallParams(
            server_name=server_name,
            tool_name=tool_name,
            arguments=arguments,
        )

        side_effect = classify_side_effect(descriptor, server_name=server_name)
        risk_tier = classify_risk_tier(descriptor, side_effect=side_effect, server_name=server_name)
        pin = resolve_platform_pin(descriptor, server_name=server_name)
        if requires_interrupt_before_call(side_effect, pin=pin):
            decision = interrupt(
                {
                    "kind": "mcp_tool_approval",
                    "server_name": server_name,
                    "tool_name": tool_name,
                    "side_effect": side_effect,
                    "risk_tier": risk_tier,
                    "arguments": arguments,
                }
            )
            if not _approval_granted(decision):
                output = ResearcherOutput(
                    summary=(f"MCP tool {server_name}.{tool_name} was not approved (side_effect={side_effect})."),
                    confidence=0.0,
                    sources_used=(),
                )
                return ResearcherTaskResult(
                    task_id=task_input.task_id,
                    agent_role=self.config.role,
                    status="failure",
                    confidence=0.0,
                    requires_review=False,
                    output=output,
                    error="MCP tool call denied by human approval",
                )

        async def _handle(payload: MCPToolCallParams) -> MCPToolCallOutcome:
            return await call_mcp_tool(
                payload,
                mcp_registry,
                conversation_id=context.thread_id,
                repository=self._mcp_tool_call_repository,
            )

        outcome = cast(
            "MCPToolCallOutcome",
            await self._tool_executor.execute(
                "mcp.call",
                params,
                _handle,
                context=context,
            ),
        )

        summary = _summarize_mcp_content(
            outcome,
            max_chars=task_input.mcp_tool_output_max_chars,
            server_name=server_name,
            tool_name=tool_name,
        )
        output = ResearcherOutput(
            summary=summary,
            confidence=0.65 if not outcome.is_error else 0.2,
            sources_used=(f"mcp:{server_name}.{tool_name}",),
        )
        requires_review = outcome.is_error or output.confidence < self.config.confidence_threshold
        status: Literal["success", "failure", "partial"] = "partial" if requires_review else "success"

        return ResearcherTaskResult(
            task_id=task_input.task_id,
            agent_role=self.config.role,
            status=status,
            confidence=output.confidence,
            requires_review=requires_review,
            output=output,
            error="MCP tool returned error content" if outcome.is_error else None,
        )


def _approval_granted(decision: object) -> bool:
    """Interpret LangGraph resume payload from HITL approve/reject."""
    if isinstance(decision, dict):
        action = decision.get("action_id") or decision.get("action")
        return action in {"approve", "approved", "allow"}
    if isinstance(decision, str):
        return decision.strip().lower() in {"approve", "approved", "allow"}
    return False


def _parse_researcher_output(raw_content: str) -> ResearcherOutput:
    """Парсит JSON-ответ LLM в ResearcherOutput."""
    payload = loads_llm_json(raw_content)
    if not isinstance(payload, dict):
        raise ValueError("Researcher JSON must be an object")
    raw_sources = payload.get("sources_used", [])
    sources = tuple(str(item) for item in raw_sources) if isinstance(raw_sources, list) else tuple()

    return ResearcherOutput(
        summary=str(payload.get("summary", "No summary provided")),
        confidence=float(payload.get("confidence", 0.0)),
        sources_used=sources,
    )


def _summarize_mcp_content(
    outcome: MCPToolCallOutcome,
    *,
    max_chars: int,
    server_name: str,
    tool_name: str,
) -> str:
    """Преобразует MCP tool content в budgeted untrusted текст для downstream LLM."""
    parts: list[str] = []
    for item in outcome.content:
        text = item.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    raw = "\n".join(parts) if parts else "MCP tool returned no text content."
    fenced = wrap_untrusted_tool_output(raw, source=f"mcp:{server_name}.{tool_name}")
    return compress_worker_context(fenced, max_chars=max_chars, label="mcp")
