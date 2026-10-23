# src/palatium_ai/application/agents/researcher/mcp_path.py

"""MCP capability pipeline for Researcher (resolve → HITL → invoke → synthesize)."""

from __future__ import annotations

import json

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from langgraph.types import interrupt

from palatium_ai.application.agents.researcher.config import (
    SUMMARY_MAX_CHARS,
    researcher_completion_budget,
    researcher_llm_config,
    researcher_tool_output_budget,
)
from palatium_ai.application.agents.researcher.outcomes import failure_output, soft_empty_output
from palatium_ai.application.agents.researcher.parsing import (
    approval_granted,
    mcp_joined_text,
    mcp_payload_is_empty,
    parse_researcher_output,
    redact_mcp_arguments,
    score_mcp_tool_confidence,
    summarize_mcp_content,
)
from palatium_ai.application.agents.researcher.prompts import RESEARCHER_SYSTEM_PROMPT
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
from palatium_ai.core.observability.hop_timings import get_hop_collector
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.contracts import AgentContext
from palatium_ai.domain.agents.messages import AgentOutput
from palatium_ai.domain.agents.researcher import (
    ATTACHMENT_REFERENCE_UNRESOLVED,
    MCP_EMPTY_RESULT,
    MCP_SERVER_UNAVAILABLE,
    MCP_TOOL_ERROR,
    RESEARCHER_TOOL_ARGS_INVALID,
    ResearcherInput,
    ResearcherOutput,
)
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.domain.mcp.models import MCPToolDescriptor
from palatium_ai.domain.mcp.tool_policy import (
    classify_risk_tier,
    classify_side_effect,
    requires_interrupt_before_call,
    resolve_platform_pin,
)
from palatium_ai.domain.memory.tool_output import strip_untrusted_tool_output
from palatium_ai.domain.policies.file_reference import FileReferencePolicy
from palatium_ai.domain.policies.hop_budget import HopBudgetPolicy
from palatium_ai.domain.policies.retrieval import RetrievalPolicy
from palatium_ai.domain.policies.types import VERBATIM_EXTRACTION_CAPABILITY

if TYPE_CHECKING:
    from palatium_ai.application.services.attachment_reference_resolver import (
        AttachmentReferenceResolver,
    )
    from palatium_ai.application.services.mcp_capabilities import MCPCapabilityIndex
    from palatium_ai.domain.agents.agent_config import AgentConfig
    from palatium_ai.domain.ports.harness import HarnessPort
    from palatium_ai.domain.ports.mcp import MCPRegistryPort, McpToolCallRecorderPort

logger = get_logger(__name__)

#: Host-local tool that materialises a thread file's text (070).
_READ_ATTACHMENT_TOOL = "read_attachment"
_PLATFORM_SERVER = "platform"


@dataclass(frozen=True, slots=True)
class McpPathDeps:
    """Ports injected by ResearcherAgent for the MCP path (no ToolExecutor creation here)."""

    config: AgentConfig
    harness: HarnessPort
    mcp_registry: MCPRegistryPort
    capability_index: MCPCapabilityIndex
    tool_executor: ToolExecutor
    argument_builder: ToolArgumentBuilder
    mcp_tool_call_repository: McpToolCallRecorderPort | None
    agent_role: str
    #: Optional: required only for the thread file re-read path. Without it the
    #: worker refuses the re-read instead of letting the model invent a file id.
    file_reference_resolver: AttachmentReferenceResolver | None = None


async def _build_file_reread_arguments(
    deps: McpPathDeps,
    task_input: ResearcherInput,
    context: AgentContext,
    tool_name: str,
    task_uuid: UUID,
) -> dict[str, object] | AgentOutput:
    """Deterministic args for a thread file re-read (070, 020).

    The model never picks the file: ``attachment_id`` comes from the owner-scoped
    repository through ``AttachmentReferenceResolver``. Any failure here is a typed
    refusal with a user-facing reason — never a guess, never an invented id.
    """
    resolver = deps.file_reference_resolver
    user_id = (context.user_id or "").strip()
    if resolver is None or not user_id or not context.thread_id:
        logger.warning(
            "researcher.file_reference_unavailable",
            tool=f"{_PLATFORM_SERVER}.{tool_name}",
            task_id=task_input.task_id,
            user_id_bound=bool(user_id),
            thread_id_bound=bool(context.thread_id),
        )
        agent_metrics.record_error(deps.agent_role, "file_reference_unavailable")
        return failure_output(
            task_uuid,
            summary=(
                "Не удалось получить доступ к файлу из хранилища. Загрузите файл в этот диалог — и я разберу его содержимое."
            ),
            error=ATTACHMENT_REFERENCE_UNRESOLVED,
        )

    resolution = await resolver.resolve(
        user_id=user_id,
        thread_id=context.thread_id,
        hint_text=_file_reference_hint(task_input),
    )
    if resolution.attachment_id is None:
        logger.info(
            "researcher.file_reference_unresolved",
            status=resolution.status,
            reason=resolution.reason,
            task_id=task_input.task_id,
        )
        agent_metrics.record_error(deps.agent_role, f"file_reference_{resolution.status}")
        return failure_output(
            task_uuid,
            summary=FileReferencePolicy.refusal_message(resolution),
            error=ATTACHMENT_REFERENCE_UNRESOLVED,
        )
    return {"attachment_id": str(resolution.attachment_id), "user_id": user_id}


def _file_reference_hint(task_input: ResearcherInput) -> str:
    """Text the resolver may read a file name from: the user's own ask only.

    Assistant prose (``prior_context``) and extracted memory hints are NOT
    evidence of which file the user meant. The previous answer routinely says
    «обращение», «документ», «кодекс» in ordinary prose; feeding it here made a
    bare word resolve to an unrelated thread file and read it (cross-file
    bleed, 055/020). User asks that do not name a file fall through to the
    ``ambiguous`` refusal → file-choice card instead of a silent wrong read.
    """
    return task_input.context_packet.user_text


def _require_researcher_input(task_input: object) -> ResearcherInput:
    if not isinstance(task_input, ResearcherInput):
        msg = f"expected ResearcherInput, got {type(task_input).__name__}"
        raise TypeError(msg)
    return task_input


def _hop_blocks_last_resort(tool_name: str, *, agent_role: str) -> bool:
    """True when hop budget forbids binding a last-resort retrieval tool."""
    if not RetrievalPolicy.is_last_resort_tool(tool_name):
        return False
    hop = get_hop_collector()
    if hop is None:
        return False
    decision = HopBudgetPolicy.should_skip_last_resort_retrieval(
        hop_total_ms=hop.total_ms(),
        budget_ms=hop.budget_ms,
    )
    if not decision.degrade:
        return False
    agent_metrics.record_node_execution(agent_role, f"hop_budget_skip_{tool_name}")
    logger.info(
        "researcher.hop_budget_skip_last_resort",
        tool_name=tool_name,
        reason=decision.reason,
        hop_total_ms=hop.total_ms(),
        hop_budget_ms=hop.budget_ms,
    )
    return True


async def execute_mcp_capability(
    deps: McpPathDeps,
    task_input: object,
    context: AgentContext,
    task_uuid: UUID,
) -> AgentOutput | None:
    task_input = _require_researcher_input(task_input)
    mcp_registry = deps.mcp_registry

    binding = await resolve_mcp_tool_binding(deps, task_input)
    if binding is None:
        if deps.capability_index.degraded_servers() and task_input.context_packet.requires_mcp:
            # The turn cannot be answered without external data, and the module that
            # would supply it is down: say so instead of answering from the model alone
            # (Level 5 graceful degradation, 055).
            logger.warning(
                "researcher.mcp_degraded_no_binding",
                task_id=task_input.task_id,
                degraded_servers=list(deps.capability_index.degraded_servers()),
            )
            agent_metrics.record_error(deps.agent_role, "mcp_server_unavailable")
            return failure_output(task_uuid, summary=None, error=MCP_SERVER_UNAVAILABLE)
        return None
    server_name, tool_name = binding

    descriptor = await fetch_mcp_descriptor(deps, mcp_registry, server_name, tool_name, task_input.task_id)
    if descriptor is None:
        return None

    args_or_failure = await build_mcp_tool_arguments(deps, task_input, context, server_name, tool_name, descriptor, task_uuid)
    if isinstance(args_or_failure, AgentOutput):
        return args_or_failure
    arguments = args_or_failure

    approval_failure = ensure_mcp_hitl_approval(deps, task_input, server_name, tool_name, descriptor, arguments, task_uuid)
    if approval_failure is not None:
        return approval_failure

    outcome_or_failure = await invoke_mcp_tool(
        deps,
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

    return await mcp_outcome_to_output(deps, task_input, outcome_or_failure, server_name, tool_name, task_uuid)


async def resolve_mcp_tool_binding(
    deps: McpPathDeps,
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
        if _hop_blocks_last_resort(execution_plan.tool_name, agent_role=deps.agent_role):
            return None
        return execution_plan.server_name, execution_plan.tool_name

    try:
        binding = await deps.capability_index.resolve_best(
            task_text=task_input.context_packet.user_text,
            requested_capabilities=task_input.context_packet.candidate_capabilities,
            local_retrieval_empty=local_retrieval_empty,
        )
    except Exception:
        logger.exception("capability index resolve failed", task_id=task_input.task_id)
        agent_metrics.record_error(deps.agent_role, "capability_index_failure")
        return None

    if binding is None:
        return None
    if _hop_blocks_last_resort(binding.tool_name, agent_role=deps.agent_role):
        return None
    return binding.server_name, binding.tool_name


async def fetch_mcp_descriptor(
    deps: McpPathDeps,
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
        agent_metrics.record_error(deps.agent_role, "registry_failure")
        return None
    return descriptor


async def build_mcp_tool_arguments(
    deps: McpPathDeps,
    task_input: object,
    context: AgentContext,
    server_name: str,
    tool_name: str,
    descriptor: MCPToolDescriptor,
    task_uuid: UUID,
) -> dict[str, object] | AgentOutput:
    task_input = _require_researcher_input(task_input)
    if server_name == _PLATFORM_SERVER and tool_name == _READ_ATTACHMENT_TOOL:
        return await _build_file_reread_arguments(deps, task_input, context, tool_name, task_uuid)
    try:
        return await deps.argument_builder.build_arguments(
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
        agent_metrics.record_error(deps.agent_role, "ToolArgumentBuildError")
        return failure_output(
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
        agent_metrics.record_error(deps.agent_role, "args_build_unexpected")
        return failure_output(
            task_uuid,
            summary=(f"Could not build valid arguments for MCP tool {server_name}.{tool_name}. No tool call was executed."),
            error=RESEARCHER_TOOL_ARGS_INVALID,
        )


def ensure_mcp_hitl_approval(
    deps: McpPathDeps,
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
        return failure_output(
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
        agent_metrics.record_error(deps.agent_role, "risk_or_hitl_failure")
        return failure_output(
            task_uuid,
            summary=(f"MCP tool {server_name}.{tool_name} could not be prepared for execution. No tool call was executed."),
            error="MCP tool risk/approval stage failed",
        )


async def invoke_mcp_tool(
    deps: McpPathDeps,
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
            repository=deps.mcp_tool_call_repository,
        )

    try:
        outcome = await deps.tool_executor.try_execute(
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
        agent_metrics.record_error(deps.agent_role, "tool_executor_failure")
        return failure_output(
            task_uuid,
            summary=(f"MCP tool {server_name}.{tool_name} execution failed. No tool result was produced."),
            error="MCP tool call execution failed",
        )

    if isinstance(outcome, ToolRbacDenied):
        agent_metrics.record_error(deps.agent_role, "ToolRbacDenied")
        return failure_output(
            task_uuid,
            summary=(f"MCP tool {server_name}.{tool_name} was denied by RBAC. No tool call was executed."),
            error=outcome.message or "tool RBAC denied",
        )

    return outcome


async def mcp_outcome_to_output(
    deps: McpPathDeps,
    task_input: object,
    outcome: MCPToolCallOutcome,
    server_name: str,
    tool_name: str,
    task_uuid: UUID,
) -> AgentOutput:
    task_input = _require_researcher_input(task_input)
    raw = mcp_joined_text(outcome)
    if outcome.error_code == "server_unavailable":
        logger.warning(
            "researcher.mcp_server_unavailable",
            tool=f"{server_name}.{tool_name}",
            task_id=str(task_uuid),
        )
        return failure_output(task_uuid, summary=None, error=MCP_SERVER_UNAVAILABLE)
    if outcome.is_error:
        return failure_output(task_uuid, summary=None, error=MCP_TOOL_ERROR)
    if mcp_payload_is_empty(raw):
        logger.warning(
            "researcher.mcp_empty_result",
            tool=f"{server_name}.{tool_name}",
            task_id=str(task_uuid),
        )
        return soft_empty_output(task_uuid, error=MCP_EMPTY_RESULT)
    source = f"mcp:{server_name}.{tool_name}"
    if _verbatim_requested(task_input):
        return _verbatim_mcp_output(
            raw,
            source=source,
            task_uuid=task_uuid,
            confidence_threshold=deps.config.confidence_threshold,
        )
    return await synthesize_mcp_output(
        deps,
        task_input,
        outcome,
        server_name=server_name,
        tool_name=tool_name,
        source=source,
        task_uuid=task_uuid,
    )


async def synthesize_mcp_output(
    deps: McpPathDeps,
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
        max_chars=researcher_tool_output_budget(
            server_name=server_name,
            tool_name=tool_name,
            default_max_chars=task_input.mcp_tool_output_max_chars,
        ),
        server_name=server_name,
        tool_name=tool_name,
    )
    llm_config = researcher_llm_config(
        deps.config,
        strategy=task_input.context_packet.execution_plan.strategy,
    )
    try:
        completion = await deps.harness.call_llm(
            llm_config,
            _synthesis_messages(task_input, tool_result=fenced, source=source),
            response_format="json_object",
            max_tokens=researcher_completion_budget(task_input.context_packet.candidate_capabilities),
        )
        output = parse_researcher_output(completion.content)
    except Exception:
        logger.exception("researcher MCP synthesis failed", task_id=str(task_uuid))
        agent_metrics.record_error(deps.agent_role, "llm_stage_failure")
        return failure_output(task_uuid, summary=None, error="LLM stage failed in researcher agent")
    sources = output.sources_used or (source,)
    output = ResearcherOutput(
        summary=output.summary,
        confidence=output.confidence,
        sources_used=sources,
        grounding_satisfied=True,
        grounding_degraded=False,
        cannot_answer_without_source=False,
    )
    agent_metrics.record_grounding_satisfied()
    status: Literal["success", "failure", "partial"] = (
        "partial" if output.confidence < deps.config.confidence_threshold else "success"
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
        logger.warning(
            "researcher.mcp_empty_result",
            tool=source,
            task_id=str(task_uuid),
        )
        return soft_empty_output(task_uuid, error=MCP_EMPTY_RESULT)
    if len(body) > SUMMARY_MAX_CHARS:
        body = body[:SUMMARY_MAX_CHARS].rstrip() + "…"
    confidence = score_mcp_tool_confidence(is_error=False, summary_chars=len(body))
    output = ResearcherOutput(
        summary=body,
        confidence=confidence,
        sources_used=(source,),
        grounding_satisfied=True,
    )
    agent_metrics.record_grounding_satisfied()
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
        "attached_files": task_input.context_packet.untrusted_context,
        "previous_answer": task_input.prior_context,
        "revision_feedback": task_input.revision_feedback,
        "user_facts": list(task_input.memory_hints[:4]),
        "mcp_tool_result": tool_result,
        "mcp_source": source,
    }
    return [
        ChatMessage(role="system", content=RESEARCHER_SYSTEM_PROMPT),
        ChatMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
    ]
