# src/palatium_ai/application/orchestration/selectors.py

"""Typed helpers для чтения данных из AgentGraphState."""

from __future__ import annotations

from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.application.services.context_packet_factory import ContextPacketFactory
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.execution import ExecutionStrategy
from palatium_ai.domain.agents.intent import IntentTaskResult, TaskKind
from palatium_ai.domain.agents.supervisor import SupervisorTaskResult, WorkerRoute
from palatium_ai.domain.memory.budget import MemoryPromptBudget
from palatium_ai.domain.memory.contextualizer import ContinuationKind
from palatium_ai.domain.memory.continuity import ContinuityPolicy, EffectiveRoutingIntent
from palatium_ai.domain.memory.tool_output import compress_worker_context

_CONTEXT_PACKET_FACTORY = ContextPacketFactory()


def _prompt_budget(state: AgentGraphState) -> MemoryPromptBudget:
    budget = state.get("prompt_budget")
    if isinstance(budget, MemoryPromptBudget):
        return budget
    return MemoryPromptBudget()


def prompt_budget(state: AgentGraphState) -> MemoryPromptBudget:
    """Return graph prompt budget (public accessor for node_inputs)."""
    return _prompt_budget(state)


def _clip_worker_text(state: AgentGraphState, text: str | None) -> str | None:
    if text is None or not text.strip():
        return text
    budget = _prompt_budget(state)
    return compress_worker_context(
        text,
        max_chars=budget.worker_summary_max_chars,
        label="worker",
    )


def resolved_user_text(state: AgentGraphState) -> str:
    """Rewritten query if Contextualizer ran, else raw user_text."""
    effective = state.get("effective_user_text")
    if isinstance(effective, str) and effective.strip():
        return effective
    return state["user_text"]


def routing_intent(state: AgentGraphState) -> EffectiveRoutingIntent | None:
    """ContinuityPolicy result (single source of truth when present)."""
    return state.get("routing_intent")


def ensure_routing_intent(state: AgentGraphState) -> EffectiveRoutingIntent:
    """Возвращает routing_intent или вычисляет ContinuityPolicy на лету."""
    existing = routing_intent(state)
    if existing is not None:
        return existing
    ctx = state.get("contextualization")
    classification = state.get("classification")
    return ContinuityPolicy.resolve(
        contextualizer=ctx.output if ctx is not None else None,
        dialog=state.get("dialog_window"),
        raw_intent=classification.output if classification is not None else None,
    )


def resolved_prior_assistant_content(state: AgentGraphState) -> str | None:
    """Prior assistant text from ContinuityPolicy / dialog."""
    intent = routing_intent(state)
    prior: str | None
    if intent is not None and intent.prior_context:
        prior = intent.prior_context
    else:
        ctx = state.get("contextualization")
        prior = ContinuityPolicy.prior_assistant_content(
            ctx.output if ctx is not None else None,
            state.get("dialog_window"),
        )
    if prior is None:
        return None
    budget = _prompt_budget(state)
    # Worker-trusted prior often holds pasted user documents — do not clip to chat excerpt.
    max_chars = budget.prior_excerpt_max_chars
    if intent is not None and intent.trust_prior_for_workers:
        max_chars = max(max_chars, budget.worker_summary_max_chars)
    return compress_worker_context(
        prior,
        max_chars=max_chars,
        label="prior",
    )


def resolved_continuation_kind(state: AgentGraphState) -> ContinuationKind | None:
    """Contextualizer / policy continuation kind."""
    intent = routing_intent(state)
    if intent is not None:
        return intent.continuation_kind
    ctx = state.get("contextualization")
    if ctx is None or ctx.output is None:
        return None
    return ctx.output.continuation_kind


def resolved_revision_feedback(state: AgentGraphState) -> str | None:
    """Human quality-reject feedback for worker revision pass, if any."""
    raw = state.get("revision_feedback")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()[:4_000]
    return None


def resolved_thread_id(state: AgentGraphState) -> str:
    """Возвращает thread id с fallback на task id."""
    return state.get("thread_id", state["task_id"])


def classification_result(state: AgentGraphState) -> IntentTaskResult:
    """Возвращает обязательный classification result."""
    return state["classification"]


def routing_result(state: AgentGraphState) -> SupervisorTaskResult | None:
    """Возвращает routing result, если он есть."""
    return state.get("routing")


def resolved_task_kind(state: AgentGraphState) -> TaskKind:
    """Task kind из ContinuityPolicy (не raw Intent)."""
    return ensure_routing_intent(state).task_kind


def resolved_requires_mcp(state: AgentGraphState) -> bool:
    """MCP flag из ContinuityPolicy."""
    return ensure_routing_intent(state).requires_mcp


def requires_user_choice(state: AgentGraphState) -> bool:
    """Exclusive selection axis from ContinuityPolicy (HITL cards, not text menus)."""
    return ensure_routing_intent(state).requires_user_choice


def resolved_candidate_capabilities(state: AgentGraphState) -> tuple[str, ...]:
    """Capabilities из ContinuityPolicy."""
    return ensure_routing_intent(state).candidate_capabilities


def resolved_reasoning(state: AgentGraphState) -> str:
    """Reasoning: ContinuityPolicy, иначе raw Intent."""
    intent = routing_intent(state)
    if intent is not None:
        return intent.reasoning
    classification = classification_result(state)
    return classification.output.reasoning if classification.output is not None else "No reasoning"


def suppress_intent_hitl(state: AgentGraphState) -> bool:
    """Return whether Intent requires_review must not seed Formatter HITL."""
    return ensure_routing_intent(state).suppress_intent_hitl


def resolved_route(state: AgentGraphState) -> WorkerRoute:
    """Возвращает route supervisor-а или fallback."""
    routing = routing_result(state)
    return routing.output.route if routing is not None and routing.output is not None else "clarification"


def resolved_route_plan(state: AgentGraphState) -> str:
    """Возвращает route plan supervisor-а или fallback."""
    routing = routing_result(state)
    return routing.output.plan if routing is not None and routing.output is not None else "No route plan"


def resolved_worker_summary(state: AgentGraphState) -> str | None:
    """Worker summary или prior context для format/answer без researcher."""
    execution = state.get("execution")
    if execution is not None and execution.output is not None:
        return _clip_worker_text(state, execution.output.summary)
    intent = ensure_routing_intent(state)
    if intent.trust_prior_for_workers:
        return _clip_worker_text(state, intent.prior_context)
    return resolved_prior_assistant_content(state)


def resolved_critic_summary(state: AgentGraphState) -> str | None:
    """Возвращает summary critic-а, если он был."""
    critic = state.get("critic")
    return critic.output.summary if critic is not None and critic.output is not None else None


def resolved_context_packet(
    state: AgentGraphState,
    *,
    fallback_strategy: ExecutionStrategy,
    fallback_rationale: str,
) -> ContextPacket:
    """Возвращает ContextPacket из context bundle или синтезирует fallback."""
    context_bundle = state.get("context_bundle")
    if context_bundle is not None and context_bundle.output is not None:
        return context_bundle.output.context_packet

    classification = classification_result(state)
    effective = ensure_routing_intent(state)
    return _CONTEXT_PACKET_FACTORY.from_state(
        task_id=classification.task_id,
        user_text=resolved_user_text(state),
        classification=classification,
        routing=routing_result(state),
        fallback_strategy=fallback_strategy,
        fallback_rationale=fallback_rationale,
        effective_task_kind=effective.task_kind,
        effective_requires_mcp=effective.requires_mcp,
        effective_capabilities=effective.candidate_capabilities,
    )


def selected_strategy(state: AgentGraphState) -> ExecutionStrategy:
    """Возвращает выбранную execution strategy после ContextWeaver."""
    context_bundle = state.get("context_bundle")
    if context_bundle is None or context_bundle.output is None:
        # Fail-open to reason_only; ContinuityPolicy/Supervisor own real clarify.
        return "reason_only"
    return context_bundle.output.execution_bundle.selected_strategy
