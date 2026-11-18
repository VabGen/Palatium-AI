# src/palatium_ai/application/agents/researcher/agent.py

"""Researcher — BaseAgent implementation (030)."""

from __future__ import annotations

import asyncio
import time

from typing import TYPE_CHECKING
from uuid import UUID

from palatium_ai.application.agents.researcher.llm_research import run_llm_research
from palatium_ai.application.agents.researcher.mcp_path import McpPathDeps, execute_mcp_capability
from palatium_ai.application.agents.researcher.outcomes import failure_output
from palatium_ai.application.agents.researcher.parsing import (
    FAILURE_PLACEHOLDER_SUMMARY,
    decode_researcher_input,
)
from palatium_ai.application.services.mcp_capabilities import MCPCapabilityIndex
from palatium_ai.application.services.tool_argument_builder import ToolArgumentBuilder
from palatium_ai.application.tools.executor import ToolExecutor
from palatium_ai.core.config import get_settings
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.adaptive_grounding import is_adaptive_grounding_enabled
from palatium_ai.core.observability.grounding_guardrail import maybe_judge
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.redaction import bucket_len, hash8
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.contracts import AgentContext
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.agents.researcher import ResearcherInput, ResearcherOutput
from palatium_ai.domain.llm.models import DocumentPart, ImagePart
from palatium_ai.domain.mcp.discovery_policy import McpDiscoveryPolicy
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.policies.researcher_observation import ResearcherObservationPolicy

if TYPE_CHECKING:
    from palatium_ai.application.services.attachment_reference_resolver import (
        AttachmentReferenceResolver,
    )
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
        file_reference_resolver: AttachmentReferenceResolver | None = None,
    ) -> None:
        super().__init__(harness, config)
        self._llm = llm
        self._mcp_registry = mcp_registry
        self._mcp_tool_call_repository = mcp_tool_call_repository
        self._file_reference_resolver = file_reference_resolver
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
            "project_agents_md",
        ]

    def get_available_tools(self) -> list[str]:
        return list(self._config.allowed_tools)

    async def verify(self, output: AgentOutput) -> bool:
        """Rule-based grounding check — reject success that claims evidence it lacks."""
        if not isinstance(output.output, ResearcherOutput):
            return False
        body = output.output
        if body.cannot_answer_without_source and output.status == "success":
            return False
        summary = body.summary.strip()
        if not summary or summary == FAILURE_PLACEHOLDER_SUMMARY:
            return False
        return not (body.grounding_satisfied and not body.sources_used)

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

        task_input = self._maybe_force_attachment_read(task_input)
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
                        file_reference_resolver=self._file_reference_resolver,
                    ),
                    task_input,
                    context,
                    input.task_id,
                    image_parts=input.image_parts,
                    document_parts=input.document_parts,
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
                handled = await self._maybe_adaptive_empty(
                    mcp_result,
                    task_input=task_input,
                    context=context,
                    skill_catalog=input.context.get("skill_catalog", ""),
                    project_agents_md=input.context.get("project_agents_md", ""),
                    task_id=input.task_id,
                    image_parts=input.image_parts,
                    document_parts=input.document_parts,
                )
                if handled is not None:
                    return handled
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
            project_agents_md=input.context.get("project_agents_md", ""),
            task_id=input.task_id,
            agent_role=self._config.role,
            image_parts=input.image_parts,
            document_parts=input.document_parts,
        )

    async def _maybe_adaptive_empty(
        self,
        mcp_result: AgentOutput,
        *,
        task_input: ResearcherInput,
        context: AgentContext,
        skill_catalog: str,
        task_id: UUID,
        image_parts: tuple[ImagePart, ...] = (),
        document_parts: tuple[DocumentPart, ...] = (),
        project_agents_md: str = "",
    ) -> AgentOutput | None:
        """Empty MCP → stub (flag off), degrade LLM (optional), or clarification (required)."""
        from palatium_ai.application.agents.researcher.outcomes import required_empty_clarification_output
        from palatium_ai.domain.agents.researcher import MCP_EMPTY_RESULT
        from palatium_ai.domain.policies.grounding import GroundingPolicy

        if mcp_result.error_message != MCP_EMPTY_RESULT:
            return None
        enabled = is_adaptive_grounding_enabled(context.user_id)
        decision = GroundingPolicy.decide_empty_retrieval(
            enabled=enabled,
            grounding=task_input.context_packet.grounding,
        )
        # ``grounding`` is a validated Literal (never empty), so no fallback is needed.
        mode: str = task_input.context_packet.grounding
        user_text = task_input.context_packet.user_text
        if decision.action == "stub":
            logger.warning(
                "researcher.grounding_stub",
                task_id=str(task_id),
                grounding=mode,
                fallback_disabled=True,
                adaptive_grounding_enabled=False,
            )
            agent_metrics.record_grounding_flag_off()
            return None

        started = time.perf_counter()
        if decision.action == "clarify":
            logger.info(
                "grounding.clarification_emitted",
                query_hash=hash8(user_text),
                len_bucket=bucket_len(user_text),
                reason="required_empty",
            )
            agent_metrics.record_grounding_clarification(
                query_hash=hash8(user_text),
                len_bucket=bucket_len(user_text),
            )
            agent_metrics.record_grounding_required_empty()
            question = GroundingPolicy.required_empty_clarification(user_text)
            result = required_empty_clarification_output(task_id, question=question)
            agent_metrics.record_grounding_latency(
                mode=mode,
                degraded=True,
                duration_seconds=time.perf_counter() - started,
            )
            return result
        logger.warning(
            "researcher.grounding_degraded",
            task_id=str(task_id),
            grounding=mode,
            reason=decision.reason,
        )
        result = await run_llm_research(
            config=self._config,
            harness=self._harness,
            tool_executor=self._tool_executor,
            mcp_registry=self._mcp_registry,
            mcp_tool_call_repository=self._mcp_tool_call_repository,
            task_input=task_input,
            context=context,
            skill_catalog=skill_catalog,
            project_agents_md=project_agents_md,
            task_id=task_id,
            agent_role=self._config.role,
            grounding_degraded=True,
            image_parts=image_parts,
            document_parts=document_parts,
        )
        agent_metrics.record_grounding_latency(
            mode=mode,
            degraded=True,
            duration_seconds=time.perf_counter() - started,
        )
        summary = ""
        if isinstance(result.output, object) and hasattr(result.output, "summary"):
            summary = str(getattr(result.output, "summary", "") or "")
        sample_rate = get_settings().observability.grounding_judge_sample_rate
        # Fire-and-forget: hold a strong ref until done so the task is not GC'd (RUF006).
        judge_task = asyncio.create_task(
            maybe_judge(user_text, summary, sample_rate),
            name="grounding.maybe_judge",
        )
        judge_task.add_done_callback(lambda _t: None)
        return result

    @staticmethod
    def _maybe_force_attachment_read(task_input: ResearcherInput) -> ResearcherInput:
        """Truncated/NOTICE fences must not stay on reason_only dump (JIT re-read, 065)."""
        from palatium_ai.domain.policies.file_reference import FileReferencePolicy

        plan = task_input.context_packet.execution_plan
        already = plan.server_name == "platform" and plan.tool_name == "read_attachment"
        if not ResearcherObservationPolicy.should_force_read_plan(
            attached_files=task_input.context_packet.untrusted_context,
            already_direct_read=already,
        ):
            return task_input
        seal = FileReferencePolicy.seals_thread_file_body(
            candidate_capabilities=task_input.context_packet.candidate_capabilities,
            response_shape=task_input.context_packet.response_shape,
        )
        forced = ToolExecutionPlan(
            strategy="direct_tool_call" if seal else "retrieve_then_reason",
            capability="attachments",
            server_name="platform",
            tool_name="read_attachment",
            requires_tool_call=True,
            rationale=(
                "Observation policy: attachment evidence is truncated or missing text; "
                "JIT platform.read_attachment instead of answering from a head/tail dump."
                + (
                    " Intent tagged verbatim_extraction: seal the body."
                    if seal
                    else " Synthesize over the full body after the re-read."
                )
            ),
        )
        packet = task_input.context_packet.model_copy(update={"execution_plan": forced, "requires_mcp": True})
        logger.info(
            "researcher.force_attachment_read",
            task_id=task_input.task_id,
            prior_strategy=plan.strategy,
            seal=seal,
        )
        return task_input.model_copy(update={"context_packet": packet})
