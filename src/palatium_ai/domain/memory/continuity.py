# src/palatium_ai/domain/memory/continuity.py

"""Единая политика непрерывности диалога.

IntentClassifier намеренно history-blind (Context Dumping anti-pattern).
ContinuityPolicy — единственный слой, который видит prior dialog и может:

1. Прикрепить prior_context к worker'ам (trust_prior_for_workers).
2. Подавить ложный HITL Intent на follow-up (suppress_intent_hitl).
3. Применить *операцию* continuity, которую Intent не может увидеть без истории:
   - format + prior → response_formatting
   - answer + refers_to_prior + clarification_needed → knowledge_request
     (history-blind Intent думает, что фактов нет, хотя они в prior)

Source polarity for prior_context (workers):
- Default: last assistant turn / Contextualizer excerpt (reformat / anaphora).
- When follow-up trusts prior AND a prior *user* turn is substantially richer than
  the assistant turn (e.g. user pasted a document, assistant only asked for input),
  prefer that user payload. Structural length heuristic — no phrase lists.

Что ContinuityPolicy НЕ делает:
- Не переписывает task_kind в knowledge_request «потому что есть диалог».
- Не классифицирует phatic/social/capability — это зона Intent.
- Не эскалирует в Researcher / Critic LLM / HITL сама по себе.
- Не снимает requires_user_choice: exclusive selection остаётся HITL-карточками.

continuation_kind — сигнал о *зависимости от prior*, не о *типе задачи*.
requires_user_choice — сигнал Intent о *обязательном выборе*; Continuity форсит
clarification_needed (кроме tool/format осей) и не глушит HITL на answer follow-up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from palatium_ai.domain.agents.intent import TaskKind
from palatium_ai.domain.memory.contextualizer import ContinuationKind

if TYPE_CHECKING:
    from palatium_ai.domain.agents.intent import IntentClassifierOutput
    from palatium_ai.domain.memory.contextualizer import ContextualizerOutput
    from palatium_ai.domain.memory.turns import DialogTurnWindow

# User turn shorter than this is not treated as a document/payload source.
_MIN_USER_PAYLOAD_CHARS = 400
# Prefer user payload when it is clearly richer than assistant prior.
_USER_OVER_ASSISTANT_RATIO = 2


class EffectiveRoutingIntent(BaseModel):
    """Нормализованный routing intent после ContinuityPolicy (single source of truth)."""

    model_config = {"frozen": True}

    task_kind: TaskKind
    requires_mcp: bool = False
    requires_user_choice: bool = False
    candidate_capabilities: tuple[str, ...] = ()
    continuation_kind: ContinuationKind = "new_topic"
    prior_context: str | None = Field(default=None, max_length=16_000)
    # Intent may set requires_review due to history-blind clarify — suppress for follow-ups.
    suppress_intent_hitl: bool = False
    trust_prior_for_workers: bool = False
    reasoning: str = Field(min_length=1, max_length=2000)


class ContinuityPolicy:
    """Чистая доменная политика: Contextualizer + dialog + raw Intent → EffectiveRoutingIntent."""

    @staticmethod
    def prior_assistant_content(
        contextualizer: ContextualizerOutput | None,
        dialog: DialogTurnWindow | None,
    ) -> str | None:
        """Excerpt из Contextualizer, иначе последняя assistant-реплика."""
        if contextualizer is not None:
            excerpt = contextualizer.prior_assistant_excerpt
            if isinstance(excerpt, str) and excerpt.strip():
                return excerpt.strip()
        if dialog is None:
            return None
        for turn in reversed(dialog.turns):
            if turn.role == "assistant" and turn.content.strip():
                return turn.content.strip()
        return None

    @staticmethod
    def prior_user_content(
        dialog: DialogTurnWindow | None,
        *,
        min_chars: int = _MIN_USER_PAYLOAD_CHARS,
    ) -> str | None:
        """Most recent substantive user turn (document / payload), if any."""
        if dialog is None:
            return None
        threshold = max(1, min_chars)
        for turn in reversed(dialog.turns):
            if turn.role != "user":
                continue
            text = turn.content.strip()
            if len(text) >= threshold:
                return text
        return None

    @classmethod
    def resolve_worker_prior(
        cls,
        *,
        assistant_prior: str | None,
        dialog: DialogTurnWindow | None,
        continuation_kind: ContinuationKind,
        trust_prior_for_workers: bool,
    ) -> str | None:
        """Choose source material for workers when continuity trusts prior.

        Prefer a prior user payload when it is substantially richer than the
        assistant prior (pasted document vs thin clarify/ack). Otherwise keep
        assistant prior (reformat / anaphora on last answer).
        """
        if not trust_prior_for_workers:
            return assistant_prior
        if continuation_kind not in {"answer", "format"}:
            return assistant_prior

        user_prior = cls.prior_user_content(dialog)
        if user_prior is None:
            return assistant_prior

        asst = (assistant_prior or "").strip()
        if not asst:
            return user_prior[:16_000]
        if len(user_prior) >= max(len(asst) * _USER_OVER_ASSISTANT_RATIO, _MIN_USER_PAYLOAD_CHARS):
            return user_prior[:16_000]
        return assistant_prior

    @staticmethod
    def _choice_caps(caps: tuple[str, ...], *, requires_user_choice: bool) -> tuple[str, ...]:
        if not requires_user_choice:
            return caps
        if "user_choice" in {item.strip().lower() for item in caps}:
            return caps
        return (*caps, "user_choice")

    @classmethod
    def _apply_user_choice_axis(
        cls,
        *,
        task_kind: TaskKind,
        requires_mcp: bool,
        requires_user_choice: bool,
        caps: tuple[str, ...],
        reasoning: str,
    ) -> tuple[TaskKind, bool, tuple[str, ...], str]:
        """Exclusive selection is clarification UX — not a knowledge dump.

        When Intent marks requires_user_choice, force clarification_needed so
        Supervisor routes clarify and HITL mints cards. Do not remapa that into
        knowledge_request later in this method.
        """
        effective_caps = cls._choice_caps(caps, requires_user_choice=requires_user_choice)
        if not requires_user_choice:
            return task_kind, requires_mcp, effective_caps, reasoning
        if task_kind in {
            "tool_execution",
            "multi_step_workflow",
            "response_formatting",
            "capability_discovery",
        }:
            # Keep tool/format axes; HITL still mints from the flag.
            return task_kind, requires_mcp, effective_caps, f"{reasoning}; requires_user_choice"
        return (
            "clarification_needed",
            False,
            effective_caps,
            f"{reasoning}; requires_user_choice → clarification_needed",
        )

    @classmethod
    def resolve(
        cls,
        *,
        contextualizer: ContextualizerOutput | None,
        dialog: DialogTurnWindow | None,
        raw_intent: IntentClassifierOutput | None,
    ) -> EffectiveRoutingIntent:
        """Сводит continuity + Intent в один EffectiveRoutingIntent."""
        assistant_prior = cls.prior_assistant_content(contextualizer, dialog)
        kind: ContinuationKind = contextualizer.continuation_kind if contextualizer is not None else "new_topic"
        refers_to_prior = bool(contextualizer.refers_to_prior) if contextualizer is not None else False
        raw_task: TaskKind = raw_intent.task_kind if raw_intent is not None else "clarification_needed"
        requires_mcp = raw_intent.requires_mcp if raw_intent is not None else False
        requires_user_choice = bool(raw_intent.requires_user_choice) if raw_intent is not None else False
        caps = raw_intent.candidate_capabilities if raw_intent is not None else ()
        intent_reasoning = raw_intent.reasoning if raw_intent is not None else "no intent"

        # Format is a continuity *operation*: Intent cannot see prior without history.
        if kind == "format" and assistant_prior is not None:
            prior = cls.resolve_worker_prior(
                assistant_prior=assistant_prior,
                dialog=dialog,
                continuation_kind=kind,
                trust_prior_for_workers=True,
            )
            source = "user_payload" if prior != assistant_prior else "assistant"
            return EffectiveRoutingIntent(
                task_kind="response_formatting",
                requires_mcp=False,
                requires_user_choice=requires_user_choice,
                candidate_capabilities=cls._choice_caps(("format",), requires_user_choice=requires_user_choice),
                continuation_kind=kind,
                prior_context=prior,
                suppress_intent_hitl=True,
                trust_prior_for_workers=True,
                reasoning=f"continuity=format; prior={source}; intent was {raw_task}",
            )

        # Format without assistant prior but with user payload (document still in thread).
        if kind == "format":
            user_prior = cls.prior_user_content(dialog)
            if user_prior is not None:
                return EffectiveRoutingIntent(
                    task_kind="response_formatting",
                    requires_mcp=False,
                    requires_user_choice=requires_user_choice,
                    candidate_capabilities=cls._choice_caps(("format",), requires_user_choice=requires_user_choice),
                    continuation_kind=kind,
                    prior_context=user_prior[:16_000],
                    suppress_intent_hitl=True,
                    trust_prior_for_workers=True,
                    reasoning=f"continuity=format; prior=user_payload; intent was {raw_task}",
                )

        # Answer continuity: enrich with prior; correct only history-blind false clarify.
        # Do NOT remapa social / capability / tool / workflow → knowledge_request.
        # Do NOT remapa exclusive-choice menus into knowledge_request.
        if (
            kind == "answer"
            and refers_to_prior
            and (assistant_prior is not None or cls.prior_user_content(dialog) is not None)
        ):
            if raw_task == "clarification_needed" and not requires_user_choice:
                task_kind: TaskKind = "knowledge_request"
                effective_caps = caps or ("summarize",)
                reasoning = (
                    f"continuity=answer; corrected history-blind clarify → knowledge_request; {intent_reasoning}"
                )
            else:
                task_kind = raw_task
                effective_caps = caps
                reasoning = f"continuity=answer; trust intent task_kind={raw_task}; {intent_reasoning}"
            task_kind, requires_mcp, effective_caps, reasoning = cls._apply_user_choice_axis(
                task_kind=task_kind,
                requires_mcp=requires_mcp,
                requires_user_choice=requires_user_choice,
                caps=effective_caps,
                reasoning=reasoning,
            )
            prior = cls.resolve_worker_prior(
                assistant_prior=assistant_prior,
                dialog=dialog,
                continuation_kind=kind,
                trust_prior_for_workers=True,
            )
            source = "user_payload" if prior and prior != assistant_prior else "assistant"
            return EffectiveRoutingIntent(
                task_kind=task_kind,
                requires_mcp=requires_mcp,
                requires_user_choice=requires_user_choice,
                candidate_capabilities=effective_caps,
                continuation_kind=kind,
                prior_context=prior,
                suppress_intent_hitl=not requires_user_choice,
                trust_prior_for_workers=True,
                reasoning=f"{reasoning}; prior={source}",
            )

        if kind == "clarify":
            return EffectiveRoutingIntent(
                task_kind="clarification_needed",
                requires_mcp=False,
                requires_user_choice=requires_user_choice,
                candidate_capabilities=cls._choice_caps((), requires_user_choice=requires_user_choice),
                continuation_kind=kind,
                prior_context=assistant_prior,
                suppress_intent_hitl=False,
                trust_prior_for_workers=False,
                reasoning=f"continuity=clarify; {intent_reasoning}",
            )

        task_kind, requires_mcp, effective_caps, reasoning = cls._apply_user_choice_axis(
            task_kind=raw_task,
            requires_mcp=requires_mcp,
            requires_user_choice=requires_user_choice,
            caps=caps,
            reasoning=f"continuity={kind}; trust intent: {intent_reasoning}",
        )
        # new_topic, answer without refers_to_prior, or format/answer without prior: trust Intent
        return EffectiveRoutingIntent(
            task_kind=task_kind,
            requires_mcp=requires_mcp,
            requires_user_choice=requires_user_choice,
            candidate_capabilities=effective_caps,
            continuation_kind=kind,
            prior_context=assistant_prior,
            suppress_intent_hitl=False,
            trust_prior_for_workers=False,
            reasoning=reasoning,
        )
