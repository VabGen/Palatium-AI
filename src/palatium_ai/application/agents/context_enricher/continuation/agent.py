# src/palatium_ai/application/agents/context_enricher/continuation/agent.py

"""Continuation phase — BaseAgent (pre-intent continuation_kind axis, 055)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING

from palatium_ai.application.agents.context_enricher.continuation.parsing import parse_contextualizer_output
from palatium_ai.application.agents.context_enricher.continuation.prompts import CONTEXTUALIZER_SYSTEM_PROMPT
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.base import BaseAgent
from palatium_ai.domain.agents.intent import TaskKind
from palatium_ai.domain.agents.messages import AgentInput, AgentOutput
from palatium_ai.domain.hitl.choice_resume import ChoiceResumePolicy, ParsedHitlChoiceResume
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.domain.memory.budget import MemoryPromptBudget, clip_memory_hints
from palatium_ai.domain.memory.contextualizer import ContextualizerOutput
from palatium_ai.domain.memory.turns import DialogTurnWindow
from palatium_ai.domain.policies import ContextualizerPolicy, ContinuityPolicy

if TYPE_CHECKING:
    from palatium_ai.domain.agents.agent_config import AgentConfig

logger = get_logger(__name__)

_FALLBACK_CONFIDENCE = 0.4
_EXCERPT_MAX_CHARS = 1500


class ContextualizerAgent(BaseAgent):
    """Rewrites underspecified follow-ups using last-K turns (continuation axis)."""

    @property
    def config(self) -> AgentConfig:
        return self._config

    def get_required_context_keys(self) -> list[str]:
        return [
            "dialog_window_json",
            "memory_hints_json",
            "prompt_budget_json",
            "task_kind",
            "requires_mcp",
        ]

    def get_available_tools(self) -> list[str]:
        return []

    @traceable(name="context_enricher.continuation.run")
    async def run(self, input: AgentInput) -> AgentOutput:
        agent_metrics.record_node_execution(self._config.role, "continuation")
        dialog_window = DialogTurnWindow.model_validate_json(input.context["dialog_window_json"])
        memory_hints = tuple(json.loads(input.context["memory_hints_json"]))
        prompt_budget = MemoryPromptBudget.model_validate_json(input.context["prompt_budget_json"])
        task_kind_raw = input.context.get("task_kind") or ""
        task_kind: TaskKind | None = task_kind_raw if task_kind_raw else None  # type: ignore[assignment]
        requires_mcp = input.context.get("requires_mcp", "false").lower() == "true"

        # Typed HITL choice resume: never ask LLM — envelope kind=clarify means slot filled.
        hitl_resume = ChoiceResumePolicy.try_parse_graph_user_text(input.instruction)
        if hitl_resume is not None:
            return _hitl_choice_resume_output(input, dialog_window, hitl_resume)

        has_assistant_prior = any(turn.role == "assistant" for turn in dialog_window.turns)
        gate = ContextualizerPolicy.decide(
            has_assistant_prior=has_assistant_prior,
            task_kind=task_kind,
            requires_mcp=requires_mcp,
        )
        if not gate.invoke_llm:
            output = ContextualizerOutput(
                rewritten_query=input.instruction,
                continuation_kind="new_topic",
                confidence=1.0,
                refers_to_prior=False,
                prior_assistant_excerpt=None,
                reasoning=f"ContextualizerPolicy pass-through ({gate.reason}).",
            )
            return AgentOutput(
                task_id=input.task_id,
                status="success",
                confidence=output.confidence,
                output=output,
            )

        dialog_history = dialog_window.as_prompt_block(
            max_chars=prompt_budget.dialog_max_chars,
            per_turn_max_chars=prompt_budget.per_turn_max_chars,
            user_turn_max_chars=prompt_budget.user_turn_max_chars,
        )
        clipped_hints = clip_memory_hints(
            memory_hints,
            max_items=prompt_budget.memory_max_items,
            max_chars=prompt_budget.memory_max_chars,
        )
        user_payload = {
            "user_text": input.instruction,
            "dialog_history": dialog_history,
            "memory_hints": list(clipped_hints),
        }
        messages = [
            ChatMessage(role="system", content=CONTEXTUALIZER_SYSTEM_PROMPT),
            ChatMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
        ]

        try:
            completion = await self._harness.call_llm(
                self._config,
                messages,
                response_format="json_object",
            )
        except Exception:
            logger.exception("context enricher continuation LLM failed", task_id=str(input.task_id))
            agent_metrics.record_error(self._config.role, "continuation_llm_failure")
            return _fallback_agent_output(input, dialog_window, reason="llm_stage_failure")

        try:
            output = parse_contextualizer_output(completion.content, dialog_window=dialog_window)
        except ValueError as exc:
            logger.warning(
                "context enricher continuation parse failed",
                task_id=str(input.task_id),
                error=str(exc)[:300],
            )
            agent_metrics.record_error(self._config.role, "continuation_parse_fallback")
            return _fallback_agent_output(input, dialog_window, reason=f"parse_failed: {exc}")

        return AgentOutput(
            task_id=input.task_id,
            status="success",
            confidence=output.confidence,
            output=output,
        )


def _prior_user_ask(dialog_window: DialogTurnWindow) -> str | None:
    """Most recent user turn that is not a HITL choice envelope."""
    for turn in reversed(dialog_window.turns):
        if turn.role != "user":
            continue
        text = turn.content.strip()
        if not text or "HITL_CHOICE_RESUME" in text:
            continue
        return text
    return None


def _hitl_choice_resume_output(
    input: AgentInput,
    dialog_window: DialogTurnWindow,
    parsed: ParsedHitlChoiceResume,
) -> AgentOutput:
    prior = ContinuityPolicy.prior_assistant_content(None, dialog_window)
    rewritten = ChoiceResumePolicy.rewrite_query_for_resume(
        parsed=parsed,
        prior_user_text=_prior_user_ask(dialog_window),
        prior_assistant_excerpt=prior,
    )
    kind = ChoiceResumePolicy.continuation_kind_for(parsed.resume_kind)
    output = ContextualizerOutput(
        rewritten_query=rewritten,
        continuation_kind=kind,
        confidence=1.0,
        refers_to_prior=True,
        prior_assistant_excerpt=(prior[:_EXCERPT_MAX_CHARS] if prior else None),
        reasoning=(
            f"deterministic HITL choice resume kind={parsed.resume_kind} action_id={parsed.action_id}; slot filled."
        ),
        choice_slot_filled=True,
    )
    return AgentOutput(
        task_id=input.task_id,
        status="success",
        confidence=output.confidence,
        output=output,
    )


def _fallback_agent_output(
    input: AgentInput,
    dialog_window: DialogTurnWindow,
    *,
    reason: str,
) -> AgentOutput:
    prior = ContinuityPolicy.prior_assistant_content(None, dialog_window)
    if prior is not None:
        output = ContextualizerOutput(
            rewritten_query=input.instruction,
            continuation_kind="answer",
            confidence=_FALLBACK_CONFIDENCE,
            refers_to_prior=True,
            prior_assistant_excerpt=prior[:_EXCERPT_MAX_CHARS],
            reasoning=f"Contextualizer fallback ({reason}); prior dialog preserved.",
        )
    else:
        output = ContextualizerOutput(
            rewritten_query=input.instruction,
            continuation_kind="new_topic",
            confidence=_FALLBACK_CONFIDENCE,
            refers_to_prior=False,
            prior_assistant_excerpt=None,
            reasoning=f"Contextualizer fallback ({reason}).",
        )
    return AgentOutput(
        task_id=input.task_id,
        status="partial",
        confidence=output.confidence,
        output=output,
        error_message=reason,
    )
