# src/palatium_ai/application/agents/researcher/agent.py

"""Researcher — BaseAgent implementation (030)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.application.agents.researcher.llm_research import run_llm_research
from palatium_ai.application.agents.researcher.mcp_path import McpPathDeps, execute_mcp_capability
from palatium_ai.application.agents.researcher.outcomes import failure_output
from palatium_ai.application.agents.researcher.parsing import decode_researcher_input
from palatium_ai.application.services.mcp_capabilities import MCPCapabilityIndex
from palatium_ai.application.services.tool_argument_builder import ToolArgumentBuilder
from palatium_ai.application.tools.executor import ToolExecutor
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.contracts import AgentContext
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.mcp.discovery_policy import McpDiscoveryPolicy

if TYPE_CHECKING:
    from palatium_ai.domain.agents.agent_config import AgentConfig
    from palatium_ai.domain.ports.harness import HarnessPort
    from palatium_ai.domain.ports.llm import LLMPort
    from palatium_ai.domain.ports.mcp import MCPRegistryPort, McpToolCallRecorderPort

logger = get_logger(__name__)


class ResearcherAgent(BaseAgent):
    """Исполняет platform-level research/orchestration-prep задачи."""

    def __init__(
        self,
        harness: HarnessPort,
        config: AgentConfig,
        llm: LLMPort,
        mcp_registry: MCPRegistryPort | None = None,
        *,
        mcp_tool_call_repository: McpToolCallRecorderPort | None = None,
        capability_index: MCPCapabilityIndex | None = None,
    ) -> None:
        super().__init__(harness, config)
        self._llm = llm
        self._mcp_registry = mcp_registry
        self._mcp_tool_call_repository = mcp_tool_call_repository
        self._tool_executor = ToolExecutor(self._config)
        self._capability_index: MCPCapabilityIndex | None
        if capability_index is not None:
            self._capability_index = capability_index
        elif mcp_registry is not None:
            self._capability_index = MCPCapabilityIndex(mcp_registry)
        else:
            self._capability_index = None
        self._argument_builder = ToolArgumentBuilder(llm)

    @property
    def config(self) -> AgentConfig:
        return self._config

    def get_required_context_keys(self) -> list[str]:
        return [
            "context_packet_json",
            "prior_context",
            "mcp_tool_output_max_chars",
            "revision_feedback",
            "skill_catalog",
            "memory_hints_json",
            "dialog_window_json",
        ]

    def get_available_tools(self) -> list[str]:
        return list(self._config.allowed_tools)

    @traceable(name="researcher.run")
    async def run(self, input: AgentInput) -> AgentOutput:
        agent_metrics.record_node_execution(self._config.role, "run")
        task_input = decode_researcher_input(input.context)
        thread_id = input.context.get("_thread_id", "unknown")
        context = AgentContext(
            thread_id=thread_id,
            user_id=(input.context.get("_user_id") or "").strip() or None,
            org_id=(input.context.get("_org_id") or "").strip() or None,
        )

        execution_plan = task_input.context_packet.execution_plan
        mcp_gate = McpDiscoveryPolicy.should_attempt_tool_execution(
            requires_mcp=task_input.context_packet.requires_mcp,
            requires_tool_call=execution_plan.requires_tool_call,
            selected_strategy=execution_plan.strategy,
        )
        if mcp_gate.allowed:
            if self._mcp_registry is None or self._capability_index is None:
                # The plan mandates a tool call, but the runtime wired no MCP registry/index (070).
                return failure_output(
                    input.task_id,
                    summary="Required MCP capability is unavailable. No tool result was produced.",
                    error="MCP capability unavailable",
                )
            try:
                mcp_result = await execute_mcp_capability(
                    McpPathDeps(
                        config=self._config,
                        harness=self._harness,
                        mcp_registry=self._mcp_registry,
                        capability_index=self._capability_index,
                        tool_executor=self._tool_executor,
                        argument_builder=self._argument_builder,
                        mcp_tool_call_repository=self._mcp_tool_call_repository,
                        agent_role=self._config.role,
                    ),
                    task_input,
                    context,
                    input.task_id,
                )
            except Exception:
                logger.exception("uncovered MCP path error", task_id=str(input.task_id))
                agent_metrics.record_error(self._config.role, "mcp_path_uncovered")
                return failure_output(
                    input.task_id,
                    summary=None,
                    error="MCP capability stage failed unexpectedly",
                )
            if mcp_result is not None:
                return mcp_result
            # MCP was attempted but produced no usable result (no binding / descriptor / outcome).
            return failure_output(
                input.task_id,
                summary="Required MCP capability is unavailable. No tool result was produced.",
                error="MCP capability unavailable",
            )

        # mcp_gate refused the tool path. That is a *policy decision* (intent needs no MCP, or the
        # route strategy deliberately answers without a tool call), not a capability failure.
        # Treating it as one killed the node in <5 ms without a single LLM call and retried it
        # three times (055: false escalation). Fall through to the ordinary LLM research path.
        logger.debug(
            "researcher MCP path skipped by policy",
            reason=mcp_gate.reason,
            strategy=execution_plan.strategy,
            task_id=str(input.task_id),
        )

        return await run_llm_research(
            config=self._config,
            harness=self._harness,
            tool_executor=self._tool_executor,
            mcp_registry=self._mcp_registry,
            mcp_tool_call_repository=self._mcp_tool_call_repository,
            task_input=task_input,
            context=context,
            skill_catalog=input.context.get("skill_catalog", ""),
            task_id=input.task_id,
            agent_role=self._config.role,
        )
