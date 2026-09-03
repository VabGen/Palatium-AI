# src/palatium_ai/domain/policies/continuity.py

"""Единая политика непрерывности диалога.

IntentClassifier намеренно history-blind (Context Dumping anti-pattern).
ContinuityPolicy — единственный слой, который видит prior dialog и может:

1. Прикрепить prior_context к worker'ам (trust_prior_for_workers).
2. Подавить ложный HITL Intent на follow-up (suppress_intent_hitl).
3. Применить *операцию* continuity, которую Intent не может увидеть без истории:
   - format + prior → response_formatting
   - answer + refers_to_prior + clarification_needed → knowledge_request
     (history-blind Intent думает, что фактов нет, хотя они в prior)

Choice / underspecification remapping is owned solely by UserChoiceIntentPolicy
(called from Continuity after continuity ops). Continuity does not duplicate that axis.

Source polarity for prior_context (workers):
- Default: last assistant turn / Contextualizer excerpt (reformat / anaphora).
- When follow-up trusts prior AND a prior *user* turn is substantially richer than
  the assistant turn (e.g. user pasted a document, assistant only asked for input),
  prefer that user payload. Structural length heuristic — no phrase lists.

Что ContinuityPolicy НЕ делает:
- Не переписывает task_kind в knowledge_request «потому что есть диалог».
- Не классифицирует phatic/social/capability — это зона Intent.
- Не эскалирует в Researcher / Critic LLM / HITL сама по себе.
- Не снимает requires_user_choice: exclusive selection остаётся HITL-карточками —
  кроме completed HITL pick (Contextualizer.choice_slot_filled): слот уже заполнен.

continuation_kind — сигнал о *зависимости от prior*, не о *типе задачи*.
requires_user_choice — сигнал Intent о *обязательном выборе*; Continuity форсит
suppress_intent_hitl=False when choice is required on trusted-prior paths.
underspecification_kind — форма незавершённости (none|open_text|discrete_choice);
discrete_choice сохраняется и не remap'ится в knowledge_request, кроме
choice_slot_filled (слот закрыт после клика по карточке).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.agents.user_choice_intent import UserChoiceIntentPolicy
from palatium_ai.domain.memory.budget import DEFAULT_PROMPT_BUDGET
from palatium_ai.domain.policies.types import ContinuationKind, TaskKind, UnderspecificationKind

if TYPE_CHECKING:
    from palatium_ai.domain.memory.contextualizer import ContextualizerOutput
    from palatium_ai.domain.memory.turns import DialogTurnWindow

# User turn shorter than this is not treated as a document/payload source.
_MIN_USER_PAYLOAD_CHARS = 400
# Prefer user payload when it is clearly richer than assistant prior.
_USER_OVER_ASSISTANT_RATIO = 2
_PRIOR_CAP = DEFAULT_PROMPT_BUDGET.worker_summary_max_chars


class EffectiveRoutingIntent(BaseModel):
    """Нормализованный routing intent после ContinuityPolicy (single source of truth)."""

    model_config = {"frozen": True}

    task_kind: TaskKind
    requires_mcp: bool = False
    requires_user_choice: bool = False
    underspecification_kind: UnderspecificationKind = "none"
    candidate_capabilities: tuple[str, ...] = ()
    continuation_kind: ContinuationKind = "new_topic"
    prior_context: str | None = Field(default=None, max_length=_PRIOR_CAP)
    # Intent may set requires_review due to history-blind clarify — suppress for follow-ups.
    suppress_intent_hitl: bool = False
    trust_prior_for_workers: bool = False
    reasoning: str = Field(min_length=1, max_length=2000)


class ContinuityPolicy:
    """Чистая доменная политика: Contextualizer + dialog + raw Intent → EffectiveRoutingIntent."""

    @staticmethod
    def _clip_prior(text: str | None) -> str | None:
        if text is None:
            return None
        stripped = text.strip()
        if not stripped:
            return None
        if len(stripped) <= _PRIOR_CAP:
            return stripped
        return stripped[:_PRIOR_CAP]

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
            return cls._clip_prior(assistant_prior)
        if continuation_kind not in {"answer", "format"}:
            return cls._clip_prior(assistant_prior)

        user_prior = cls.prior_user_content(dialog)
        if user_prior is None:
            return cls._clip_prior(assistant_prior)

        asst = (assistant_prior or "").strip()
        if not asst:
            return cls._clip_prior(user_prior)
        if len(user_prior) >= max(len(asst) * _USER_OVER_ASSISTANT_RATIO, _MIN_USER_PAYLOAD_CHARS):
            return cls._clip_prior(user_prior)
        return cls._clip_prior(assistant_prior)

    @classmethod
    def _finalize(
        cls,
        *,
        task_kind: TaskKind,
        requires_mcp: bool,
        requires_user_choice: bool,
        underspec: UnderspecificationKind,
        caps: tuple[str, ...],
        continuation_kind: ContinuationKind,
        prior_context: str | None,
        trust_prior_for_workers: bool,
        reasoning: str,
        confidence: float,
        clarify_underspec_default: bool = False,
    ) -> EffectiveRoutingIntent:
        """Apply UserChoiceIntentPolicy (sole choice-axis owner) then build routing intent."""
        if clarify_underspec_default and underspec == "none":
            underspec = "discrete_choice" if requires_user_choice else "open_text"

        normalized = UserChoiceIntentPolicy.normalize(
            IntentClassifierOutput(
                task_kind=task_kind,
                requires_mcp=requires_mcp,
                requires_user_choice=requires_user_choice,
                underspecification_kind=underspec,
                candidate_capabilities=caps,
                confidence=max(0.0, min(1.0, confidence)),
                reasoning=(reasoning or "continuity")[:2000],
            )
        )
        # Trusted-prior follow-ups suppress history-blind Intent review unless choice HITL.
        suppress = trust_prior_for_workers and not normalized.requires_user_choice
        return EffectiveRoutingIntent(
            task_kind=normalized.task_kind,
            requires_mcp=normalized.requires_mcp,
            requires_user_choice=normalized.requires_user_choice,
            underspecification_kind=normalized.underspecification_kind,
            candidate_capabilities=normalized.candidate_capabilities,
            continuation_kind=continuation_kind,
            prior_context=cls._clip_prior(prior_context),
            suppress_intent_hitl=suppress,
            trust_prior_for_workers=trust_prior_for_workers,
            reasoning=normalized.reasoning,
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
        underspec: UnderspecificationKind = raw_intent.underspecification_kind if raw_intent is not None else "none"
        caps = raw_intent.candidate_capabilities if raw_intent is not None else ()
        intent_reasoning = raw_intent.reasoning if raw_intent is not None else "no intent"
        confidence = float(raw_intent.confidence) if raw_intent is not None else 1.0
        choice_slot_filled = bool(contextualizer.choice_slot_filled) if contextualizer is not None else False
        # Completed HITL discrete pick: never re-open exclusive choice.
        if choice_slot_filled:
            requires_user_choice = False
            underspec = "none"

        # Format is a continuity *operation*: Intent cannot see prior without history.
        if kind == "format" and assistant_prior is not None:
            prior = cls.resolve_worker_prior(
                assistant_prior=assistant_prior,
                dialog=dialog,
                continuation_kind=kind,
                trust_prior_for_workers=True,
            )
            source = "user_payload" if prior != cls._clip_prior(assistant_prior) else "assistant"
            return cls._finalize(
                task_kind="response_formatting",
                requires_mcp=False,
                requires_user_choice=requires_user_choice,
                underspec=underspec,
                caps=("format",),
                continuation_kind=kind,
                prior_context=prior,
                trust_prior_for_workers=True,
                reasoning=f"continuity=format; prior={source}; intent was {raw_task}",
                confidence=confidence,
            )

        # Format without assistant prior but with user payload (document still in thread).
        if kind == "format":
            user_prior = cls.prior_user_content(dialog)
            if user_prior is not None:
                return cls._finalize(
                    task_kind="response_formatting",
                    requires_mcp=False,
                    requires_user_choice=requires_user_choice,
                    underspec=underspec,
                    caps=("format",),
                    continuation_kind=kind,
                    prior_context=user_prior,
                    trust_prior_for_workers=True,
                    reasoning=f"continuity=format; prior=user_payload; intent was {raw_task}",
                    confidence=confidence,
                )

        # Answer continuity: enrich with prior; correct only history-blind false clarify.
        # Do NOT remapa social / capability / tool / workflow → knowledge_request.
        # Do NOT remapa exclusive-choice menus into knowledge_request (unless slot filled).
        if (
            kind == "answer"
            and refers_to_prior
            and (assistant_prior is not None or cls.prior_user_content(dialog) is not None)
        ):
            if choice_slot_filled and raw_task == "clarification_needed":
                task_kind: TaskKind = "knowledge_request"
                effective_caps = tuple(c for c in caps if c != "user_choice") or ("summarize",)
                reasoning = f"continuity=answer; HITL choice slot filled → knowledge_request; {intent_reasoning}"
            elif raw_task == "clarification_needed" and not requires_user_choice and underspec != "discrete_choice":
                task_kind = "knowledge_request"
                effective_caps = caps or ("summarize",)
                reasoning = (
                    f"continuity=answer; corrected history-blind clarify → knowledge_request; {intent_reasoning}"
                )
            else:
                task_kind = raw_task
                effective_caps = caps
                reasoning = f"continuity=answer; trust intent task_kind={raw_task}; {intent_reasoning}"
            prior = cls.resolve_worker_prior(
                assistant_prior=assistant_prior,
                dialog=dialog,
                continuation_kind=kind,
                trust_prior_for_workers=True,
            )
            source = "user_payload" if prior and prior != cls._clip_prior(assistant_prior) else "assistant"
            return cls._finalize(
                task_kind=task_kind,
                requires_mcp=requires_mcp,
                requires_user_choice=requires_user_choice,
                underspec=underspec,
                caps=effective_caps,
                continuation_kind=kind,
                prior_context=prior,
                trust_prior_for_workers=True,
                reasoning=f"{reasoning}; prior={source}",
                confidence=confidence,
            )

        if kind == "clarify":
            return cls._finalize(
                task_kind="clarification_needed",
                requires_mcp=False,
                requires_user_choice=requires_user_choice,
                underspec=underspec,
                caps=(),
                continuation_kind=kind,
                prior_context=assistant_prior,
                trust_prior_for_workers=False,
                reasoning=f"continuity=clarify; {intent_reasoning}",
                confidence=confidence,
                clarify_underspec_default=True,
            )

        # new_topic, answer without refers_to_prior, or format/answer without prior: trust Intent
        return cls._finalize(
            task_kind=raw_task,
            requires_mcp=requires_mcp,
            requires_user_choice=requires_user_choice,
            underspec=underspec,
            caps=caps,
            continuation_kind=kind,
            prior_context=assistant_prior,
            trust_prior_for_workers=False,
            reasoning=f"continuity={kind}; trust intent: {intent_reasoning}",
            confidence=confidence,
        )
