# src/palatium_ai/application/agents/researcher/agent.py

"""Researcher — BaseAgent implementation (030)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from langgraph.types import interrupt

from palatium_ai.application.agents.researcher.config import SUMMARY_MAX_CHARS, researcher_completion_budget
from palatium_ai.application.agents.researcher.parsing import (
    FAILURE_PLACEHOLDER_SUMMARY,
    approval_granted,
    decode_researcher_input,
    mcp_joined_text,
    mcp_payload_is_empty,
    parse_researcher_output,
    redact_mcp_arguments,
    score_mcp_tool_confidence,
    summarize_mcp_content,
)
from palatium_ai.application.agents.researcher.prompts import RESEARCHER_SYSTEM_PROMPT
from palatium_ai.application.agents.skill_hydrate import hydrate_skill_references
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
from palatium_ai.domain.agents.researcher import (
    MCP_EMPTY_RESULT,
    MCP_TOOL_ERROR,
    RESEARCHER_TOOL_ARGS_INVALID,
    ResearcherInput,
    ResearcherOutput,
)
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.domain.mcp.discovery_policy import McpDiscoveryPolicy
from palatium_ai.domain.mcp.models import MCPToolDescriptor
from palatium_ai.domain.mcp.tool_policy import (
    classify_risk_tier,
    classify_side_effect,
    requires_interrupt_before_call,
    resolve_platform_pin,
)
from palatium_ai.domain.memory.tool_output import strip_untrusted_tool_output
from palatium_ai.domain.policies.retrieval import RetrievalPolicy
from palatium_ai.domain.policies.types import VERBATIM_EXTRACTION_CAPABILITY

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
                return _failure_output(
                    input.task_id,
                    summary="Required MCP capability is unavailable. No tool result was produced.",
                    error="MCP capability unavailable",
                )
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
            # MCP was attempted but produced no usable result (no binding / descriptor / outcome).
            return _failure_output(
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

        skill_catalog = input.context.get("skill_catalog", "")
        skill_references = await hydrate_skill_references(
            catalog_text=skill_catalog,
            user_text=task_input.context_packet.user_text,
            tool_executor=self._tool_executor,
            mcp_registry=self._mcp_registry,
            context=context,
            repository=self._mcp_tool_call_repository,
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
                        "attachment_context": task_input.context_packet.untrusted_context,
                        "prior_context": task_input.prior_context,
                        "revision_feedback": task_input.revision_feedback,
                        "memory_hints": list(task_input.memory_hints[:4]),
                        "skill_catalog": skill_catalog,
                        "skill_references": skill_references,
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
                max_tokens=researcher_completion_budget(task_input.context_packet.candidate_capabilities),
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

        args_or_failure = await self._build_mcp_tool_arguments(task_input, context, server_name, tool_name, descriptor, task_uuid)
        if isinstance(args_or_failure, AgentOutput):
            return args_or_failure
        arguments = args_or_failure

        approval_failure = self._ensure_mcp_hitl_approval(task_input, server_name, tool_name, descriptor, arguments, task_uuid)
        if approval_failure is not None:
            return approval_failure

        outcome_or_failure = await self._invoke_mcp_tool(
            task_input,
            context,
            server_name,
            tool_name,
            arguments,
            mcp_registry,
            task_uuid,
            allow_unpinned=resolve_platform_pin(descriptor, server_name=server_name) is None,
        )
        if isinstance(outcome_or_failure, AgentOutput):
            return outcome_or_failure

        return await self._mcp_outcome_to_output(task_input, outcome_or_failure, server_name, tool_name, task_uuid)

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
            binding = await self._capability_index.resolve_best(  # type: ignore[union-attr]  # индекс проверен вызывающим (017)
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
                summary=(f"Could not build valid arguments for MCP tool {server_name}.{tool_name}. No tool call was executed."),
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
                summary=(f"Could not build valid arguments for MCP tool {server_name}.{tool_name}. No tool call was executed."),
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
                summary=(f"MCP tool {server_name}.{tool_name} could not be prepared for execution. No tool call was executed."),
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
        *,
        allow_unpinned: bool = False,
    ) -> MCPToolCallOutcome | AgentOutput:
        task_input = _require_researcher_input(task_input)
        params = MCPToolCallParams(
            server_name=server_name,
            tool_name=tool_name,
            arguments=arguments,
            actor_user_id=(context.user_id or "").strip(),
            actor_org_id=(context.org_id or "").strip(),
            actor_thread_id=context.thread_id,
            allow_unpinned=allow_unpinned,
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

    async def _mcp_outcome_to_output(
        self,
        task_input: object,
        outcome: MCPToolCallOutcome,
        server_name: str,
        tool_name: str,
        task_uuid: UUID,
    ) -> AgentOutput:
        task_input = _require_researcher_input(task_input)
        raw = mcp_joined_text(outcome)
        if outcome.is_error:
            return _failure_output(task_uuid, summary=None, error=MCP_TOOL_ERROR)
        if mcp_payload_is_empty(raw):
            return _failure_output(task_uuid, summary=None, error=MCP_EMPTY_RESULT)
        source = f"mcp:{server_name}.{tool_name}"
        if _verbatim_requested(task_input):
            return _verbatim_mcp_output(
                raw,
                source=source,
                task_uuid=task_uuid,
                confidence_threshold=self._config.confidence_threshold,
            )
        return await self._synthesize_mcp_output(
            task_input,
            outcome,
            server_name=server_name,
            tool_name=tool_name,
            source=source,
            task_uuid=task_uuid,
        )

    async def _synthesize_mcp_output(
        self,
        task_input: ResearcherInput,
        outcome: MCPToolCallOutcome,
        *,
        server_name: str,
        tool_name: str,
        source: str,
        task_uuid: UUID,
    ) -> AgentOutput:
        """Second agent-loop step: the tool body stays in the prompt, the model writes summary."""
        fenced = summarize_mcp_content(
            outcome,
            max_chars=task_input.mcp_tool_output_max_chars,
            server_name=server_name,
            tool_name=tool_name,
        )
        try:
            completion = await self._harness.call_llm(
                self._config,
                _synthesis_messages(task_input, tool_result=fenced, source=source),
                response_format="json_object",
                max_tokens=researcher_completion_budget(task_input.context_packet.candidate_capabilities),
            )
            output = parse_researcher_output(completion.content)
        except Exception:
            logger.exception("researcher MCP synthesis failed", task_id=str(task_uuid))
            agent_metrics.record_error(self._config.role, "llm_stage_failure")
            return _failure_output(task_uuid, summary=None, error="LLM stage failed in researcher agent")
        status: Literal["success", "failure", "partial"] = (
            "partial" if output.confidence < self._config.confidence_threshold else "success"
        )
        return AgentOutput(
            task_id=task_uuid,
            status=status,
            confidence=output.confidence,
            output=output,
        )


def _verbatim_requested(task_input: ResearcherInput) -> bool:
    caps = {item.strip().lower() for item in task_input.context_packet.candidate_capabilities}
    return VERBATIM_EXTRACTION_CAPABILITY in caps


def _verbatim_mcp_output(
    raw: str,
    *,
    source: str,
    task_uuid: UUID,
    confidence_threshold: float,
) -> AgentOutput:
    """Keep the tool body. The envelope stays out of the user-visible summary."""
    body = strip_untrusted_tool_output(raw).strip()
    if not body:
        return _failure_output(task_uuid, summary=None, error=MCP_EMPTY_RESULT)
    if len(body) > SUMMARY_MAX_CHARS:
        body = body[:SUMMARY_MAX_CHARS].rstrip() + "…"
    confidence = score_mcp_tool_confidence(is_error=False, summary_chars=len(body))
    output = ResearcherOutput(summary=body, confidence=confidence, sources_used=(source,))
    status: Literal["success", "failure", "partial"] = "partial" if confidence < confidence_threshold else "success"
    return AgentOutput(
        task_id=task_uuid,
        status=status,
        confidence=confidence,
        output=output,
    )


def _synthesis_messages(task_input: ResearcherInput, *, tool_result: str, source: str) -> list[ChatMessage]:
    """Same researcher JSON contract as the dialog path; evidence is the MCP payload."""
    payload = {
        "user_text": task_input.context_packet.user_text,
        "task_kind": task_input.context_packet.task_kind,
        "requires_mcp": task_input.context_packet.requires_mcp,
        "candidate_capabilities": list(task_input.context_packet.candidate_capabilities),
        "route_plan": task_input.context_packet.route_plan,
        "context_summary": task_input.context_packet.context_summary,
        "attachment_context": task_input.context_packet.untrusted_context,
        "prior_context": task_input.prior_context,
        "revision_feedback": task_input.revision_feedback,
        "memory_hints": list(task_input.memory_hints[:4]),
        "mcp_tool_result": tool_result,
        "mcp_source": source,
    }
    return [
        ChatMessage(role="system", content=RESEARCHER_SYSTEM_PROMPT),
        ChatMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
    ]


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
