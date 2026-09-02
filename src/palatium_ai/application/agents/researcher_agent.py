# src/palatium_ai/application/agents/researcher_agent.py

"""Агент Researcher — текстовый worker для поиска/анализа без side effects."""

from __future__ import annotations

import json
import logging

from typing import TYPE_CHECKING, Literal, cast

from langgraph.types import interrupt

from palatium_ai.application.agents.base import BaseAgent
from palatium_ai.application.services.mcp_capabilities import MCPCapabilityIndex
from palatium_ai.application.services.tool_argument_builder import (
    ToolArgumentBuilder,
    ToolArgumentBuildError,
)
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
from palatium_ai.domain.mcp.models import MCPToolDescriptor
from palatium_ai.domain.mcp.tool_policy import (
    classify_risk_tier,
    classify_side_effect,
    requires_interrupt_before_call,
    resolve_platform_pin,
)
from palatium_ai.domain.memory.tool_output import (
    compress_worker_context,
    wrap_untrusted_tool_output,
)

if TYPE_CHECKING:
    from palatium_ai.application.services.cost_budget import CostBudgetService
    from palatium_ai.domain.agents.contracts import AgentContext
    from palatium_ai.domain.ports.llm import LlmCostEstimatorPort, LLMPort
    from palatium_ai.domain.ports.mcp import MCPRegistryPort, McpToolCallRecorderPort

logger = logging.getLogger(__name__)

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

# Последняя незакрытая точка 500: ToolExecutor. Ниже — потолок summary,
# чтобы LLM-мусор в поле summary не раздул downstream-контекст.
_SUMMARY_MAX_CHARS = 4000


class ResearcherAgent(BaseAgent):
    """Исполняет platform-level research/orchestration-prep задачи.

    Контракт отказного пути: исключения никогда не покидают ``execute`` —
    каждый стейдж (LLM / capability index / registry / args / HITL /
    tool call) конвертирует отказ в ``ResearcherTaskResult(status="failure")``.
    Неожиданные ошибки логируются с traceback, ожидаемые — warning'ом.
    """

    config = RESEARCHER_CONFIG

    def __init__(
        self,
        llm: LLMPort,
        mcp_registry: MCPRegistryPort | None = None,
        *,
        mcp_tool_call_repository: McpToolCallRecorderPort | None = None,
        capability_index: MCPCapabilityIndex | None = None,
        cost_budget: CostBudgetService | None = None,
        cost_estimator: LlmCostEstimatorPort | None = None,
    ) -> None:
        super().__init__(llm, cost_budget=cost_budget, cost_estimator=cost_estimator)
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
        agent_metrics.record_node_execution("researcher", "researcher_node")

        execution_plan = task_input.context_packet.execution_plan
        mcp_gate = McpDiscoveryPolicy.should_attempt_tool_execution(
            requires_mcp=task_input.context_packet.requires_mcp,
            requires_tool_call=execution_plan.requires_tool_call,
            selected_strategy=execution_plan.strategy,
        )
        if mcp_gate.allowed and self._mcp_registry is not None and self._capability_index is not None:
            try:
                mcp_result = await self._execute_mcp_capability(task_input, context)
            except Exception:
                # страховка: непокрытый путь внутри _execute_mcp_capability
                # не должен превращаться в 500 — tamper-сигналы
                # (AuditChainIntegrityError) уже залогированы с traceback
                logger.exception("uncovered MCP path error (task=%s)", task_input.task_id)
                agent_metrics.record_error("researcher", "mcp_path_uncovered")
                return _failure_result(
                    task_input.task_id,
                    self.config.role,
                    summary=None,
                    error="MCP capability stage failed unexpectedly",
                )
            if mcp_result is not None:
                return mcp_result

        # Fail closed: never invent tool results when MCP was required or planned.
        if task_input.context_packet.requires_mcp or execution_plan.requires_tool_call:
            return _failure_result(
                task_input.task_id,
                self.config.role,
                summary="Required MCP capability is unavailable. No tool result was produced.",
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
        except Exception:
            logger.exception("researcher LLM stage failed (task=%s)", task_input.task_id)
            agent_metrics.record_error("researcher", "llm_stage_failure")
            return _failure_result(
                task_input.task_id,
                self.config.role,
                summary=None,
                error="LLM stage failed in researcher agent",
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
        """Пытается исполнить задачу через MCP capability index.

        Весь путь (резолв инструмента → аргументы → approval → call)
        защищён: ожидаемые отказы возвращают failure-result, неожиданные
        исключения логируются с traceback и тоже конвертируются в
        failure-result.
        """
        if self._mcp_registry is None or self._capability_index is None:
            return None
        mcp_registry = self._mcp_registry

        binding = await self._resolve_mcp_tool_binding(task_input)
        if binding is None:
            return None
        server_name, tool_name = binding

        descriptor = await self._fetch_mcp_descriptor(
            mcp_registry, server_name, tool_name, task_input.task_id
        )
        if descriptor is None:
            return None

        args_or_failure = await self._build_mcp_tool_arguments(
            task_input, context, server_name, tool_name, descriptor
        )
        if isinstance(args_or_failure, ResearcherTaskResult):
            return args_or_failure
        arguments = args_or_failure

        approval_failure = self._ensure_mcp_hitl_approval(
            task_input, server_name, tool_name, descriptor, arguments
        )
        if approval_failure is not None:
            return approval_failure

        outcome_or_failure = await self._invoke_mcp_tool(
            task_input, context, server_name, tool_name, arguments, mcp_registry
        )
        if isinstance(outcome_or_failure, ResearcherTaskResult):
            return outcome_or_failure

        return self._mcp_outcome_to_result(
            task_input, outcome_or_failure, server_name, tool_name
        )

    async def _resolve_mcp_tool_binding(
        self,
        task_input: ResearcherInput,
    ) -> tuple[str, str] | None:
        execution_plan = task_input.context_packet.execution_plan
        if execution_plan.requires_tool_call:
            if execution_plan.server_name is None or execution_plan.tool_name is None:
                return None
            return execution_plan.server_name, execution_plan.tool_name

        try:
            binding = await self._capability_index.resolve_best(  # type: ignore[union-attr]
                task_text=task_input.context_packet.user_text,
                requested_capabilities=task_input.context_packet.candidate_capabilities,
            )
        except Exception:
            logger.exception("capability index resolve failed (task=%s)", task_input.task_id)
            agent_metrics.record_error("researcher", "capability_index_failure")
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
                "mcp_registry.get_tool failed for %s.%s (task=%s)",
                server_name,
                tool_name,
                task_id,
            )
            agent_metrics.record_error("researcher", "registry_failure")
            return None
        return descriptor

    async def _build_mcp_tool_arguments(
        self,
        task_input: ResearcherInput,
        context: AgentContext,
        server_name: str,
        tool_name: str,
        descriptor: MCPToolDescriptor,
    ) -> dict[str, object] | ResearcherTaskResult:
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
                "args build failed for %s.%s (task=%s): %s",
                server_name,
                tool_name,
                task_input.task_id,
                exc,
            )
            agent_metrics.record_error("researcher", "ToolArgumentBuildError")
            return _failure_result(
                task_input.task_id,
                self.config.role,
                summary=(
                    f"Could not build valid arguments for MCP tool "
                    f"{server_name}.{tool_name}. No tool call was executed."
                ),
                error=RESEARCHER_TOOL_ARGS_INVALID,
            )
        except Exception:
            logger.exception(
                "unexpected error building args for %s.%s (task=%s)",
                server_name,
                tool_name,
                task_input.task_id,
            )
            agent_metrics.record_error("researcher", "args_build_unexpected")
            return _failure_result(
                task_input.task_id,
                self.config.role,
                summary=(
                    f"Could not build valid arguments for MCP tool "
                    f"{server_name}.{tool_name}. No tool call was executed."
                ),
                error=RESEARCHER_TOOL_ARGS_INVALID,
            )

    def _ensure_mcp_hitl_approval(
        self,
        task_input: ResearcherInput,
        server_name: str,
        tool_name: str,
        descriptor: MCPToolDescriptor,
        arguments: dict[str, object],
    ) -> ResearcherTaskResult | None:
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
                    "arguments": arguments,
                }
            )
            if _approval_granted(decision):
                return None
            return _failure_result(
                task_input.task_id,
                self.config.role,
                summary=(f"MCP tool {server_name}.{tool_name} was not approved (side_effect={side_effect})."),
                error="MCP tool call denied by human approval",
                requires_review=False,
            )
        except Exception:
            logger.exception(
                "risk classification / HITL approval failed for %s.%s (task=%s)",
                server_name,
                tool_name,
                task_input.task_id,
            )
            agent_metrics.record_error("researcher", "risk_or_hitl_failure")
            return _failure_result(
                task_input.task_id,
                self.config.role,
                summary=(
                    f"MCP tool {server_name}.{tool_name} could not be "
                    "prepared for execution. No tool call was executed."
                ),
                error="MCP tool risk/approval stage failed",
            )

    async def _invoke_mcp_tool(
        self,
        task_input: ResearcherInput,
        context: AgentContext,
        server_name: str,
        tool_name: str,
        arguments: dict[str, object],
        mcp_registry: MCPRegistryPort,
    ) -> MCPToolCallOutcome | ResearcherTaskResult:
        params = MCPToolCallParams(
            server_name=server_name,
            tool_name=tool_name,
            arguments=arguments,
        )

        async def _handle(payload: MCPToolCallParams) -> MCPToolCallOutcome:
            return await call_mcp_tool(
                payload,
                mcp_registry,
                conversation_id=context.thread_id,
                repository=self._mcp_tool_call_repository,
            )

        try:
            return cast(
                "MCPToolCallOutcome",
                await self._tool_executor.execute(
                    "mcp.call",
                    params,
                    _handle,
                    context=context,
                ),
            )
        except Exception:
            logger.exception(
                "tool executor failed for %s.%s (task=%s)",
                server_name,
                tool_name,
                task_input.task_id,
            )
            agent_metrics.record_error("researcher", "tool_executor_failure")
            return _failure_result(
                task_input.task_id,
                self.config.role,
                summary=(f"MCP tool {server_name}.{tool_name} execution failed. No tool result was produced."),
                error="MCP tool call execution failed",
            )

    def _mcp_outcome_to_result(
        self,
        task_input: ResearcherInput,
        outcome: MCPToolCallOutcome,
        server_name: str,
        tool_name: str,
    ) -> ResearcherTaskResult:
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


def _failure_result(
    task_id: str,
    agent_role: str,
    *,
    summary: str | None,
    error: str,
    requires_review: bool = True,
) -> ResearcherTaskResult:
    """Фабрика отказных результатов — единый набор полей на всех путях.

    output=None, когда материала для содержательного ответа нет (LLM-стейдж,
    неожиданный сбой); заполненный ResearcherOutput, когда есть что сказать
    пользователю (args invalid, approval denied).
    """
    output: ResearcherOutput | None = None
    if summary is not None:
        output = ResearcherOutput(
            summary=summary,
            confidence=0.0,
            sources_used=(),
        )
    return ResearcherTaskResult(
        task_id=task_id,
        agent_role=agent_role,
        status="failure",
        confidence=0.0,
        requires_review=requires_review,
        output=output,
        error=error,
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
    """Парсит JSON-ответ LLM в ResearcherOutput.

    Хардening против LLM-мусора: confidence клампится в [0.0, 1.0]
    (иначе NaN/1.5 ломает confidence gate и метрики), summary
    обрезается до _SUMMARY_MAX_CHARS.
    """
    payload = loads_llm_json(raw_content)
    if not isinstance(payload, dict):
        raise ValueError("Researcher JSON must be an object")

    raw_summary = payload.get("summary", "No summary provided")
    summary = str(raw_summary).strip() or "No summary provided"
    if len(summary) > _SUMMARY_MAX_CHARS:
        summary = summary[:_SUMMARY_MAX_CHARS].rstrip() + "…"

    try:
        confidence = float(payload.get("confidence", 0.0))
    except TypeError, ValueError:
        confidence = 0.0
    # math.isnan/isinf отсекают "confidence": NaN из JSON-мусора
    if confidence != confidence or confidence in (float("inf"), float("-inf")):
        confidence = 0.0
    confidence = min(max(confidence, 0.0), 1.0)

    raw_sources = payload.get("sources_used", [])
    sources = tuple(str(item) for item in raw_sources)[:10] if isinstance(raw_sources, list) else ()

    return ResearcherOutput(
        summary=summary,
        confidence=confidence,
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
