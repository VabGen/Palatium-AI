# src/palatium_ai/application/services/execution_planner.py

"""ExecutionPlanner строит execution bundle из нормализованного context packet."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from palatium_ai.application.services.mcp_capabilities import MCPCapabilityIndex
from palatium_ai.core.logging.context import user_id_var
from palatium_ai.core.observability.adaptive_grounding import is_adaptive_grounding_enabled
from palatium_ai.core.observability.file_reread_rollout import is_file_reread_enabled
from palatium_ai.domain.agents.context_weaver import ContextWeaverInput
from palatium_ai.domain.agents.workflow_policy import WorkflowExecutionPolicy
from palatium_ai.domain.mcp.discovery_policy import McpDiscoveryPolicy
from palatium_ai.domain.mcp.models import ExecutionPlanBundle, ToolExecutionPlan
from palatium_ai.domain.policies.file_reference import FileReferencePolicy
from palatium_ai.domain.policies.grounding import GroundingPolicy
from palatium_ai.domain.policies.parallel_workers import ParallelWorkerPolicy
from palatium_ai.domain.policies.types import CONTENT_GENERATION_CAPABILITY, ExecutionStrategy, TaskKind

if TYPE_CHECKING:
    from palatium_ai.domain.agents.supervisor import WorkerRoute

_CODE_CAPS: frozenset[str] = frozenset({"code", "coding", "sandbox", "code_exec"})
_ANALYST_CAPS: frozenset[str] = frozenset({"analytics", "analysis", "metrics", "trends", "stats", "statistics"})
_KNOWLEDGE_KINDS = cast(
    "frozenset[TaskKind]",
    frozenset({"knowledge_request", "tool_execution"}),
)


class ExecutionPlanner:
    """Отдельный planner, чтобы orchestration не зависел от реализации агента."""

    def __init__(self, capability_index: MCPCapabilityIndex | None = None) -> None:
        self._capability_index = capability_index

    async def build(self, task_input: ContextWeaverInput) -> ExecutionPlanBundle:
        """Возвращает execution bundle; multi-step when research∥analyst (P2.15)."""
        if task_input.route in {"clarification", "formatter"}:
            primary = await self._build_primary_step(task_input)
            return ExecutionPlanBundle(
                selected_strategy=primary.strategy,
                requires_tool_call=primary.requires_tool_call,
                steps=(primary,),
            )

        parallel = ParallelWorkerPolicy.decide_from_capabilities(
            candidate_capabilities=task_input.candidate_capabilities,
        )
        if parallel.parallel:
            research_step = await self._build_research_step(task_input)
            analyst_step = ToolExecutionPlan(
                strategy="data_analysis",
                requires_tool_call=False,
                rationale=(
                    f"Parallel multi-capability plan ({parallel.reason}): structured analysis alongside knowledge retrieval."
                ),
            )
            return ExecutionPlanBundle(
                selected_strategy=research_step.strategy,
                requires_tool_call=research_step.requires_tool_call or analyst_step.requires_tool_call,
                steps=(research_step, analyst_step),
            )

        primary_step = await self._build_primary_step(task_input)
        return ExecutionPlanBundle(
            selected_strategy=primary_step.strategy,
            requires_tool_call=primary_step.requires_tool_call,
            steps=(primary_step,),
        )

    async def _build_research_step(self, task_input: ContextWeaverInput) -> ToolExecutionPlan:
        """Knowledge/MCP path without analytics/code short-circuit (parallel half)."""
        discovered = await self._try_discovered_mcp(task_input)
        if discovered is not None:
            return discovered

        executable_kind = WorkflowExecutionPolicy.executable_task_kind(
            task_input.task_kind,
            requires_mcp=task_input.requires_mcp,
        )
        adaptive_on = is_adaptive_grounding_enabled(user_id_var.get())
        if task_input.has_attachment_context:
            return _attachment_grounded_plan(
                "Parallel research half: fenced attachment text already present; ground without search_knowledge."
            )
        if task_input.has_trusted_prior and GroundingPolicy.allows_prior_grounded_skip(
            enabled=adaptive_on,
            grounding=task_input.grounding,
        ):
            return _prior_grounded_plan(
                "Parallel research half: Continuity trusts dialog prior; answer without search_knowledge."
            )
        if task_input.requires_mcp:
            return _unresolved_mcp_or_knowledge_plan(
                grounding=task_input.grounding,
                executable_kind=executable_kind,
                parallel=True,
            )
        if adaptive_on and task_input.grounding == "none":
            return ToolExecutionPlan(
                strategy="reason_only",
                requires_tool_call=False,
                rationale=(f"Parallel research half: adaptive grounding=none (executable_kind={executable_kind})."),
            )
        return _search_knowledge_plan(
            f"Parallel research half: retrieve via platform.search_knowledge then reason "
            f"(executable_kind={executable_kind}; grounding={task_input.grounding})."
        )

    async def _build_primary_step(self, task_input: ContextWeaverInput) -> ToolExecutionPlan:
        executable_kind = WorkflowExecutionPolicy.executable_task_kind(
            task_input.task_kind,
            requires_mcp=task_input.requires_mcp,
        )

        # Route is set from the same fact (Supervisor collapses the kind), so a re-read
        # never reaches a worker that cannot call tools; the gate documents that the
        # plan and the route are one decision, not two (055).
        if task_input.route == "researcher" and _file_reread_requested(task_input) and is_file_reread_enabled(user_id_var.get()):
            return _file_reread_plan(
                plural=task_input.attachment_scope == "all",
                seal=FileReferencePolicy.seals_thread_file_body(
                    candidate_capabilities=task_input.candidate_capabilities,
                    response_shape=task_input.response_shape,
                ),
            )

        route_plan = _route_local_plan(task_input.route, executable_kind, task_input.requires_mcp)
        if route_plan is not None:
            return route_plan

        discovered = await self._try_discovered_mcp(task_input)
        if discovered is not None:
            return discovered

        cap_plan = _capability_hint_plan(task_input.candidate_capabilities)
        if cap_plan is not None:
            return cap_plan

        if executable_kind in _KNOWLEDGE_KINDS:
            return _knowledge_or_tool_plan(task_input, executable_kind)

        return ToolExecutionPlan(
            strategy="reason_only",
            requires_tool_call=False,
            rationale="No external tool required; worker can reason over current context.",
        )

    async def _try_discovered_mcp(self, task_input: ContextWeaverInput) -> ToolExecutionPlan | None:
        mcp_gate = McpDiscoveryPolicy.should_discover_capabilities(
            requires_mcp=task_input.requires_mcp,
            route=task_input.route,
        )
        if not mcp_gate.allowed or self._capability_index is None:
            return None
        binding = await self._capability_index.resolve_best(
            task_text=task_input.user_text,
            requested_capabilities=task_input.candidate_capabilities,
        )
        if binding is None:
            return None
        return ToolExecutionPlan(
            strategy="direct_tool_call",
            capability=binding.capability,
            server_name=binding.server_name,
            tool_name=binding.tool_name,
            requires_tool_call=True,
            rationale="Matching MCP capability was discovered from registered tool descriptors.",
        )


def _file_reread_requested(task_input: ContextWeaverInput) -> bool:
    """True when Continuity set ``file_reference=thread_file`` (storage re-read).

    Sticky SB2 rehydrate can set ``has_attachment_context`` from a *prior* fence
    without a fresh upload; that used to suppress ``read_attachment`` and the
    model answered «файл не приложен» after a successful unique-name re-read
    (W10.2 att_partial_name). The thread_file axis is the SoT for storage reads:
    Continuity already prefers a true this-turn fence over a stale re-read.
    """
    return task_input.file_reference == "thread_file"


def _file_reread_plan(*, plural: bool = False, seal: bool = False) -> ToolExecutionPlan:
    """Owner-scoped storage read; the reference is resolved in the worker path.

    ``plural`` marks an explicit "every file of this dialog" ask: identity is still
    resolved in the application layer, but the step covers the whole set and the
    worker issues one read per file instead of a single read and a wrong summary.

    ``seal`` (Intent ``verbatim_extraction``): the OCR body *is* the answer
    (``direct_tool_call``). Otherwise ``retrieve_then_reason`` — read then synthesize
    recommendations / summary / analysis so Formatter does not dump the raw file.
    """
    strategy: ExecutionStrategy = "direct_tool_call" if seal else "retrieve_then_reason"
    seal_note = (
        " Intent tagged verbatim_extraction: seal the extracted body as the answer."
        if seal
        else " Synthesize the answer over the retrieved body (do not dump the raw file)."
    )
    return ToolExecutionPlan(
        strategy=strategy,
        capability="attachments",
        server_name="platform",
        tool_name="read_attachment",
        requires_tool_call=True,
        rationale=(
            "Thread file re-read: the ask targets files already uploaded in this dialog; "
            "read their owner-scoped bodies from storage instead of claiming they are missing."
            + seal_note
            + (
                " The ask covers the whole set: read every file, one call per file, and answer over the combined evidence."
                if plural
                else ""
            )
        ),
    )


def _route_local_plan(
    route: WorkerRoute,
    executable_kind: TaskKind,
    requires_mcp: bool,
) -> ToolExecutionPlan | None:
    if route == "clarification":
        return ToolExecutionPlan(
            strategy="clarify",
            requires_tool_call=False,
            rationale="Supervisor marked the request as needing clarification.",
        )
    if route != "formatter":
        return None
    # Social → Formatter LLM (format_only). Canned ack_only templates are a 2024-era
    # latency shortcut that fails closed wrongly when Intent mislabels a real ask (055).
    # Fast-tier LLM for phatic is the 2026 default; keep ack_only only as an explicit
    # eval/cassette strategy, not the live planner path.
    if executable_kind == "social_conversation" and not requires_mcp:
        return ToolExecutionPlan(
            strategy="format_only",
            requires_tool_call=False,
            rationale="Phatic/social turn; Formatter LLM reply (no canned ack template).",
        )
    return ToolExecutionPlan(
        strategy="format_only",
        requires_tool_call=False,
        rationale="Task can be completed by formatting already available data.",
    )


def _capability_hint_plan(candidate_capabilities: tuple[str, ...]) -> ToolExecutionPlan | None:
    caps = {c.strip().lower() for c in candidate_capabilities}
    if caps & _CODE_CAPS:
        return ToolExecutionPlan(
            strategy="code_sandbox",
            requires_tool_call=False,
            rationale="Capability hints request a code draft/plan (sandbox exec remains HITL-gated).",
        )
    if caps & _ANALYST_CAPS:
        return ToolExecutionPlan(
            strategy="data_analysis",
            requires_tool_call=False,
            rationale="Capability hints request structured analysis without tool execution.",
        )
    return None


def _knowledge_or_tool_plan(
    task_input: ContextWeaverInput,
    executable_kind: TaskKind,
) -> ToolExecutionPlan:
    adaptive_on = is_adaptive_grounding_enabled(user_id_var.get())
    if task_input.has_attachment_context:
        return _attachment_grounded_plan(
            "Turn already carries fenced attachment text; ground the answer on upload OCR without search_knowledge."
        )
    if task_input.has_trusted_prior and GroundingPolicy.allows_prior_grounded_skip(
        enabled=adaptive_on,
        grounding=task_input.grounding,
    ):
        return _prior_grounded_plan("Continuity trusts dialog prior; answer from prior_context without search_knowledge.")
    if task_input.requires_mcp:
        return _unresolved_mcp_or_knowledge_plan(
            grounding=task_input.grounding,
            executable_kind=executable_kind,
            parallel=False,
        )
    caps = {c.strip().lower() for c in task_input.candidate_capabilities}
    if CONTENT_GENERATION_CAPABILITY in caps:
        # Creative text is generated, not retrieved: corpus hits would only pull the
        # answer toward unrelated documents. Drafts keep retrieval (they cite norms).
        return ToolExecutionPlan(
            strategy="reason_only",
            requires_tool_call=False,
            rationale="Content generation ask; compose from dialog/memory context without search_knowledge.",
        )
    if adaptive_on and task_input.grounding == "none":
        return ToolExecutionPlan(
            strategy="reason_only",
            requires_tool_call=False,
            rationale=(f"Adaptive grounding=none; reason without search_knowledge (executable_kind={executable_kind})."),
        )
    return _search_knowledge_plan(
        "Knowledge path without domain MCP binding: retrieve via "
        "platform.search_knowledge then reason "
        f"(executable_kind={executable_kind}; grounding={task_input.grounding})."
    )


def _attachment_grounded_plan(rationale: str) -> ToolExecutionPlan:
    return ToolExecutionPlan(
        strategy="reason_only",
        requires_tool_call=False,
        rationale=rationale,
    )


def _prior_grounded_plan(rationale: str) -> ToolExecutionPlan:
    return ToolExecutionPlan(
        strategy="reason_only",
        requires_tool_call=False,
        rationale=rationale,
    )


def _mcp_unresolved_plan() -> ToolExecutionPlan:
    return ToolExecutionPlan(
        strategy="reason_only",
        requires_tool_call=False,
        rationale=(
            "requires_mcp=true but no MCP capability resolved; worker must fail closed instead of inventing tool results."
        ),
    )


def _unresolved_mcp_or_knowledge_plan(
    *,
    grounding: str,
    executable_kind: TaskKind,
    parallel: bool,
) -> ToolExecutionPlan:
    """``requires_mcp`` without a domain binding.

    ClarificationGate sets ``requires_mcp=True`` + ``grounding=required`` for empty-thread
    fact asks so the turn must retrieve then refuse — not invent (W10 3b). The old
    ``_mcp_unresolved_plan`` short-circuited to ``reason_only``, and Researcher fell through
    to an unconstrained LLM answer. Platform ``search_knowledge`` is the evidence path
    when no EDMS/analytics tool bound; empty hits → GroundingPolicy clarify.
    """
    if GroundingPolicy.coerce_mode(grounding) == "required":
        prefix = "Parallel research half: " if parallel else ""
        return _search_knowledge_plan(
            f"{prefix}requires_mcp without domain binding; grounding=required → "
            f"retrieve via platform.search_knowledge then refuse on empty "
            f"(executable_kind={executable_kind})."
        )
    return _mcp_unresolved_plan()


def _search_knowledge_plan(rationale: str) -> ToolExecutionPlan:
    return ToolExecutionPlan(
        strategy="retrieve_then_reason",
        capability="knowledge",
        server_name="platform",
        tool_name="search_knowledge",
        requires_tool_call=True,
        rationale=rationale,
    )
