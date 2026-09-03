# src/palatium_ai/application/agents/researcher/agent.py

"""Researcher — BaseAgent implementation (030)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from langgraph.types import interrupt

from palatium_ai.application.agents.researcher.parsing import (
    FAILURE_PLACEHOLDER_SUMMARY,
    approval_granted,
    decode_researcher_input,
    parse_researcher_output,
    redact_mcp_arguments,
    summarize_mcp_content,
)
from palatium_ai.application.agents.researcher.prompts import RESEARCHER_SYSTEM_PROMPT
from palatium_ai.application.services.mcp_capabilities import MCPCapabilityIndex
from palatium_ai.application.services.tool_argument_builder import (
    ToolArgumentBuilder,
    ToolArgumentBuildError,
)
from palatium_ai.application.tools.executor import ToolExecutor, ToolRbacDenied
from palatium_ai.application.tools.mcp import (
    MCPToolCallOutcome,
    MCPToolCallParams,
    call_mcp_tool,
)
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.contracts import AgentContext
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.agents.researcher import RESEARCHER_TOOL_ARGS_INVALID, ResearcherInput, ResearcherOutput
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.domain.mcp.discovery_policy import McpDiscoveryPolicy
from palatium_ai.domain.mcp.models import MCPToolDescriptor
from palatium_ai.domain.mcp.tool_policy import (
    classify_risk_tier,
    classify_side_effect,
    requires_interrupt_before_call,
    resolve_platform_pin,
)
from palatium_ai.domain.policies.retrieval import RetrievalPolicy

if TYPE_CHECKING:
    from palatium_ai.domain.agents.agent_config import AgentConfig
    from palatium_ai.domain.ports.harness import HarnessPort
    from palatium_ai.domain.ports.llm import LLMPort
    from palatium_ai.domain.ports.mcp import MCPRegistryPort, McpToolCallRecorderPort

logger = get_logger(__name__)


def _require_researcher_input(task_input: object) -> ResearcherInput:
    if not isinstance(task_input, ResearcherInput):
        msg = f"expected ResearcherInput, got {type(task_input).__name__}"
        raise TypeError(msg)
    return task_input


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
        if mcp_gate.allowed and self._mcp_registry is not None and self._capability_index is not None:
            try:
                mcp_result = await self._execute_mcp_capability(task_input, context, input.task_id)
            except Exception:
                logger.exception("uncovered MCP path error", task_id=str(input.task_id))
                agent_metrics.record_error(self._config.role, "mcp_path_uncovered")
                return _failure_output(
                    input.task_id,
                    summary=None,
                    error="MCP capability stage failed unexpectedly",
                )
            if mcp_result is not None:
                return mcp_result

        if task_input.context_packet.requires_mcp or execution_plan.requires_tool_call:
            return _failure_output(
                input.task_id,
                summary="Required MCP capability is unavailable. No tool result was produced.",
                error="MCP capability unavailable",
            )

        messages = [
            ChatMessage(role="system", content=RESEARCHER_SYSTEM_PROMPT),
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
            completion = await self._harness.call_llm(
                self._config,
                messages,
                response_format="json_object",
            )
            output = parse_researcher_output(completion.content)
        except Exception:
            logger.exception("researcher LLM stage failed", task_id=str(input.task_id))
            agent_metrics.record_error(self._config.role, "llm_stage_failure")
            return _failure_output(
                input.task_id,
                summary=None,
                error="LLM stage failed in researcher agent",
            )

        requires_review = output.confidence < self._config.confidence_threshold
        status: Literal["success", "failure", "partial"] = "partial" if requires_review else "success"
        if requires_review:
            agent_metrics.record_human_escalation("low_confidence_research")

        return AgentOutput(
            task_id=input.task_id,
            status=status,
            confidence=output.confidence,
            output=output,
        )

    async def _execute_mcp_capability(
        self,
        task_input: object,
        context: AgentContext,
        task_uuid: UUID,
    ) -> AgentOutput | None:
        task_input = _require_researcher_input(task_input)
        if self._mcp_registry is None or self._capability_index is None:
            return None
        mcp_registry = self._mcp_registry

        binding = await self._resolve_mcp_tool_binding(task_input)
        if binding is None:
            return None
        server_name, tool_name = binding

        descriptor = await self._fetch_mcp_descriptor(mcp_registry, server_name, tool_name, task_input.task_id)
        if descriptor is None:
            return None

        args_or_failure = await self._build_mcp_tool_arguments(
            task_input, context, server_name, tool_name, descriptor, task_uuid
        )
        if isinstance(args_or_failure, AgentOutput):
            return args_or_failure
        arguments = args_or_failure

        approval_failure = self._ensure_mcp_hitl_approval(
            task_input, server_name, tool_name, descriptor, arguments, task_uuid
        )
        if approval_failure is not None:
            return approval_failure

        outcome_or_failure = await self._invoke_mcp_tool(
            task_input, context, server_name, tool_name, arguments, mcp_registry, task_uuid
        )
        if isinstance(outcome_or_failure, AgentOutput):
            return outcome_or_failure

        return self._mcp_outcome_to_output(task_input, outcome_or_failure, server_name, tool_name, task_uuid)

    async def _resolve_mcp_tool_binding(
        self,
        task_input: object,
    ) -> tuple[str, str] | None:
        task_input = _require_researcher_input(task_input)
        execution_plan = task_input.context_packet.execution_plan
        local_retrieval_empty = task_input.context_packet.local_retrieval_empty
        if execution_plan.requires_tool_call:
            if execution_plan.server_name is None or execution_plan.tool_name is None:
                return None
            gate = RetrievalPolicy.may_bind_tool(
                tool_name=execution_plan.tool_name,
                local_retrieval_empty=local_retrieval_empty,
            )
            if not gate.allowed:
                return None
            return execution_plan.server_name, execution_plan.tool_name

        try:
            binding = await self._capability_index.resolve_best(  # type: ignore[union-attr]
                task_text=task_input.context_packet.user_text,
                requested_capabilities=task_input.context_packet.candidate_capabilities,
                local_retrieval_empty=local_retrieval_empty,
            )
        except Exception:
            logger.exception("capability index resolve failed", task_id=task_input.task_id)
            agent_metrics.record_error(self._config.role, "capability_index_failure")
            return None

        if binding is None:
            return None
        return binding.server_name, binding.tool_name

    async def _fetch_mcp_descriptor(
        self,
        mcp_registry: MCPRegistryPort,
        server_name: str,
        tool_name: str,
        task_id: str,
    ) -> MCPToolDescriptor | None:
        try:
            descriptor = await mcp_registry.get_tool(server_name, tool_name)
        except Exception:
            logger.exception(
                "mcp_registry.get_tool failed",
                server_name=server_name,
                tool_name=tool_name,
                task_id=task_id,
            )
            agent_metrics.record_error(self._config.role, "registry_failure")
            return None
        return descriptor

    async def _build_mcp_tool_arguments(
        self,
        task_input: object,
        context: AgentContext,
        server_name: str,
        tool_name: str,
        descriptor: MCPToolDescriptor,
        task_uuid: UUID,
    ) -> dict[str, object] | AgentOutput:
        task_input = _require_researcher_input(task_input)
        try:
            return await self._argument_builder.build_arguments(
                descriptor=descriptor,
                user_text=task_input.context_packet.user_text,
                route_plan=task_input.context_packet.route_plan,
                task_kind=task_input.context_packet.task_kind,
                candidate_capabilities=task_input.context_packet.candidate_capabilities,
                conversation_id=context.thread_id,
            )
        except ToolArgumentBuildError as exc:
            logger.warning(
                "args build failed",
                server_name=server_name,
                tool_name=tool_name,
                task_id=task_input.task_id,
                error=str(exc),
            )
            agent_metrics.record_error(self._config.role, "ToolArgumentBuildError")
            return _failure_output(
                task_uuid,
                summary=(
                    f"Could not build valid arguments for MCP tool "
                    f"{server_name}.{tool_name}. No tool call was executed."
                ),
                error=RESEARCHER_TOOL_ARGS_INVALID,
            )
        except Exception:
            logger.exception(
                "unexpected error building args",
                server_name=server_name,
                tool_name=tool_name,
                task_id=task_input.task_id,
            )
            agent_metrics.record_error(self._config.role, "args_build_unexpected")
            return _failure_output(
                task_uuid,
                summary=(
                    f"Could not build valid arguments for MCP tool "
                    f"{server_name}.{tool_name}. No tool call was executed."
                ),
                error=RESEARCHER_TOOL_ARGS_INVALID,
            )

    def _ensure_mcp_hitl_approval(
        self,
        task_input: object,
        server_name: str,
        tool_name: str,
        descriptor: MCPToolDescriptor,
        arguments: dict[str, object],
        task_uuid: UUID,
    ) -> AgentOutput | None:
        task_input = _require_researcher_input(task_input)
        try:
            side_effect = classify_side_effect(descriptor, server_name=server_name)
            risk_tier = classify_risk_tier(descriptor, side_effect=side_effect, server_name=server_name)
            pin = resolve_platform_pin(descriptor, server_name=server_name)

            if not requires_interrupt_before_call(side_effect, pin=pin):
                return None

            decision = interrupt(
                {
                    "kind": "mcp_tool_approval",
                    "server_name": server_name,
                    "tool_name": tool_name,
                    "side_effect": side_effect,
                    "risk_tier": risk_tier,
                    "arguments": redact_mcp_arguments(arguments),
                    "irreversible": pin.irreversible if pin is not None else False,
                }
            )
            if approval_granted(decision):
                return None
            return _failure_output(
                task_uuid,
                summary=(f"MCP tool {server_name}.{tool_name} was not approved (side_effect={side_effect})."),
                error="MCP tool call denied by human approval",
            )
        except Exception:
            logger.exception(
                "risk classification / HITL approval failed",
                server_name=server_name,
                tool_name=tool_name,
                task_id=task_input.task_id,
            )
            agent_metrics.record_error(self._config.role, "risk_or_hitl_failure")
            return _failure_output(
                task_uuid,
                summary=(
                    f"MCP tool {server_name}.{tool_name} could not be "
                    "prepared for execution. No tool call was executed."
                ),
                error="MCP tool risk/approval stage failed",
            )

    async def _invoke_mcp_tool(
        self,
        task_input: object,
        context: AgentContext,
        server_name: str,
        tool_name: str,
        arguments: dict[str, object],
        mcp_registry: MCPRegistryPort,
        task_uuid: UUID,
    ) -> MCPToolCallOutcome | AgentOutput:
        task_input = _require_researcher_input(task_input)
        params = MCPToolCallParams(
            server_name=server_name,
            tool_name=tool_name,
            arguments=arguments,
            actor_user_id=(context.user_id or "").strip(),
            actor_org_id=(context.org_id or "").strip(),
            actor_thread_id=context.thread_id,
        )

        async def _handle(payload: MCPToolCallParams) -> MCPToolCallOutcome:
            return await call_mcp_tool(
                payload,
                mcp_registry,
                conversation_id=context.thread_id,
                repository=self._mcp_tool_call_repository,
            )

        try:
            outcome = await self._tool_executor.try_execute(
                "mcp.call",
                params,
                _handle,
                context=context,
            )
        except Exception:
            logger.exception(
                "tool executor failed",
                server_name=server_name,
                tool_name=tool_name,
                task_id=task_input.task_id,
            )
            agent_metrics.record_error(self._config.role, "tool_executor_failure")
            return _failure_output(
                task_uuid,
                summary=(f"MCP tool {server_name}.{tool_name} execution failed. No tool result was produced."),
                error="MCP tool call execution failed",
            )

        if isinstance(outcome, ToolRbacDenied):
            agent_metrics.record_error(self._config.role, "ToolRbacDenied")
            return _failure_output(
                task_uuid,
                summary=(f"MCP tool {server_name}.{tool_name} was denied by RBAC. No tool call was executed."),
                error=outcome.message or "tool RBAC denied",
            )

        return outcome

    def _mcp_outcome_to_output(
        self,
        task_input: object,
        outcome: MCPToolCallOutcome,
        server_name: str,
        tool_name: str,
        task_uuid: UUID,
    ) -> AgentOutput:
        task_input = _require_researcher_input(task_input)
        summary = summarize_mcp_content(
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
        requires_review = outcome.is_error or output.confidence < self._config.confidence_threshold
        status: Literal["success", "failure", "partial"] = "partial" if requires_review else "success"

        return AgentOutput(
            task_id=task_uuid,
            status=status,
            confidence=output.confidence,
            output=output,
            error_message="MCP tool returned error content" if outcome.is_error else None,
        )


def _failure_output(
    task_id: UUID,
    *,
    summary: str | None,
    error: str,
) -> AgentOutput:
    if summary is not None:
        output = ResearcherOutput(summary=summary, confidence=0.0, sources_used=())
    else:
        output = ResearcherOutput(
            summary=FAILURE_PLACEHOLDER_SUMMARY,
            confidence=0.0,
            sources_used=(),
        )
    return AgentOutput(
        task_id=task_id,
        status="failure",
        confidence=0.0,
        output=output,
        error_message=error,
    )
