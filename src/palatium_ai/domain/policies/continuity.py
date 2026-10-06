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
- Default: Contextualizer salient excerpt (user or assistant) / last assistant.
- Format / document: rich user paste (≥N chars and clearly richer than assistant)
  wins over thin assistant clarify/ack. Structural length heuristic — no phrase lists.
- Answer / anaphora after topic-switch: when last assistant dwarfs short user
  intents (code dump, long answer after a brief preference), prefer those user
  intents over the dump so workers see the referent, not the intervening topic.
- False clarify recovery: Contextualizer `clarify` with resolvable history
  (excerpt, refers_to_prior, or topic-switch user intents) → treat as `answer`.

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

from dataclasses import dataclass
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
# Max short user intents to bundle under a topic-switched assistant dump.
_MAX_SHORT_USER_INTENTS = 4
_PRIOR_CAP = DEFAULT_PROMPT_BUDGET.worker_summary_max_chars
_HITL_RESUME_MARKER = "HITL_CHOICE_RESUME"


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
    def resolve_effective_user_text(
        *,
        raw_user_text: str,
        rewritten_query: str,
        has_turn_attachments: bool,
    ) -> str:
        """Pick the ask text workers/HITL see for this turn.

        When fenced uploads are present, keep the raw user ask. Contextualizer is
        attachment-blind and will anaphora-bind prior assistant topics into
        ``rewritten_query`` («дай сводку» → prior file summary), which then
        frames Researcher and option synthesizer away from the new document (055).
        """
        raw = raw_user_text.strip()
        if has_turn_attachments and raw:
            return raw
        rewritten = rewritten_query.strip()
        return rewritten or raw

    @staticmethod
    def prior_assistant_content(
        contextualizer: ContextualizerOutput | None,
        dialog: DialogTurnWindow | None,
    ) -> str | None:
        """Salient excerpt from Contextualizer (user or assistant), else last assistant."""
        if contextualizer is not None:
            excerpt = contextualizer.prior_assistant_excerpt
            if isinstance(excerpt, str) and excerpt.strip():
                return excerpt.strip()
        return ContinuityPolicy.last_assistant_from_dialog(dialog)

    @staticmethod
    def last_assistant_from_dialog(dialog: DialogTurnWindow | None) -> str | None:
        """Raw last assistant turn in the window (ignores Contextualizer excerpt)."""
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
            if not text or _HITL_RESUME_MARKER in text:
                continue
            if len(text) >= threshold:
                return text
        return None

    @classmethod
    def recent_short_user_intents(
        cls,
        dialog: DialogTurnWindow | None,
        *,
        max_chars: int = _MIN_USER_PAYLOAD_CHARS,
        max_items: int = _MAX_SHORT_USER_INTENTS,
    ) -> tuple[str, ...]:
        """Recent short user turns (preferences / asks), oldest→newest, capped."""
        if dialog is None or max_items < 1:
            return ()
        cap = max(1, max_chars)
        selected: list[str] = []
        for turn in reversed(dialog.turns):
            if turn.role != "user":
                continue
            text = turn.content.strip()
            if not text or _HITL_RESUME_MARKER in text:
                continue
            if len(text) >= cap:
                continue
            selected.append(text)
            if len(selected) >= max_items:
                break
        selected.reverse()
        return tuple(selected)

    @classmethod
    def topic_switch_user_prior(
        cls,
        dialog: DialogTurnWindow | None,
        assistant_prior: str | None,
    ) -> str | None:
        """User-intent bundle when last assistant is a long topic dump vs short asks.

        Structural only: len(last_assistant) ≥ max(2× longest short user, payload floor).
        Covers anaphora to earlier user facts after an intervening long assistant turn.
        """
        intents = cls.recent_short_user_intents(dialog)
        if not intents:
            return None
        last_asst = (cls.last_assistant_from_dialog(dialog) or assistant_prior or "").strip()
        if not last_asst:
            return None
        longest = max(len(text) for text in intents)
        threshold = max(longest * _USER_OVER_ASSISTANT_RATIO, _MIN_USER_PAYLOAD_CHARS)
        if len(last_asst) < threshold:
            return None
        return cls._clip_prior("\n".join(intents))

    @classmethod
    def should_recover_false_clarify(
        cls,
        *,
        contextualizer: ContextualizerOutput | None,
        dialog: DialogTurnWindow | None,
        assistant_prior: str | None,
    ) -> bool:
        """True when history can resolve the ask — Contextualizer over-clarified."""
        if contextualizer is None:
            return False
        has_history = assistant_prior is not None or cls.prior_user_content(dialog, min_chars=1) is not None
        if not has_history:
            return False
        if (contextualizer.prior_assistant_excerpt or "").strip():
            return True
        if contextualizer.refers_to_prior:
            return True
        return cls.topic_switch_user_prior(dialog, assistant_prior) is not None

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

        Format: rich user paste over thin assistant; else assistant.
        Answer: rich paste → LLM salient excerpt (≠ raw last assistant) →
        topic-switch user intents → assistant fallback.
        """
        if not trust_prior_for_workers:
            return cls._clip_prior(assistant_prior)
        if continuation_kind not in {"answer", "format"}:
            return cls._clip_prior(assistant_prior)

        asst = (assistant_prior or "").strip()
        user_rich = cls.prior_user_content(dialog)
        if user_rich is not None:
            if not asst:
                return cls._clip_prior(user_rich)
            if len(user_rich) >= max(len(asst) * _USER_OVER_ASSISTANT_RATIO, _MIN_USER_PAYLOAD_CHARS):
                return cls._clip_prior(user_rich)

        if continuation_kind == "format":
            return cls._clip_prior(assistant_prior)

        # answer: prefer Contextualizer excerpt when it is not just the raw last assistant
        last_raw = (cls.last_assistant_from_dialog(dialog) or "").strip()
        if asst and last_raw and asst != last_raw:
            return cls._clip_prior(asst)

        topic_user = cls.topic_switch_user_prior(dialog, assistant_prior)
        if topic_user is not None:
            return topic_user
        return cls._clip_prior(assistant_prior)

    @staticmethod
    def _prior_source_label(*, prior: str | None, assistant_prior: str | None) -> str:
        clipped_asst = ContinuityPolicy._clip_prior(assistant_prior)
        if prior and prior != clipped_asst:
            return "user_payload" if len(prior) >= _MIN_USER_PAYLOAD_CHARS else "user_intents"
        return "assistant"

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
        has_turn_attachments: bool = False,
    ) -> EffectiveRoutingIntent:
        """Сводит continuity + Intent в один EffectiveRoutingIntent.

        ``has_turn_attachments``: this turn carries fenced upload text. Then
        workers must NOT bind prior assistant content, false ``discrete_choice``
        is cleared for every continuation kind, and callers should pin
        ``effective_user_text`` via ``resolve_effective_user_text`` (055).
        """
        snap = _ResolveSnapshot.from_inputs(contextualizer=contextualizer, raw_intent=raw_intent)
        assistant_prior = cls.prior_assistant_content(contextualizer, dialog)
        if snap.choice_slot_filled:
            snap.requires_user_choice = False
            snap.underspec = "none"

        recovered_false_clarify = False
        if snap.kind == "clarify" and cls.should_recover_false_clarify(
            contextualizer=contextualizer,
            dialog=dialog,
            assistant_prior=assistant_prior,
        ):
            snap.kind = "answer"
            snap.refers_to_prior = True
            recovered_false_clarify = True

        # New upload on this turn owns file-oriented asks; format/answer-of-prior
        # would summarize the previous document and may skip the researcher (055).
        # Contextualizer/Intent discrete_choice on a grounded upload ("дай сводку",
        # "дай текст из файла") is false clarify for *any* continuation_kind — the
        # fenced OCR already supplies the referent. Clearing choice only for
        # clarify left answer/format/new_topic uploads minting HITL menus about the
        # prior dialog topic (cross-file bleed via option synthesizer).
        # Drop assistant_prior entirely: otherwise fallthrough still injects the
        # previous file's answer into Researcher/Formatter.
        if has_turn_attachments:
            if snap.kind in {"format", "clarify"}:
                snap.kind = "answer"
            snap.refers_to_prior = False
            assistant_prior = None
            snap.requires_user_choice = False
            snap.underspec = "none"
            snap.caps = tuple(c for c in snap.caps if c != "user_choice")
            if snap.raw_task == "clarification_needed":
                snap.raw_task = "knowledge_request"
            recovered_false_clarify = True

        formatted = cls._try_resolve_format(snap=snap, assistant_prior=assistant_prior, dialog=dialog)
        if formatted is not None:
            return formatted

        answered = cls._try_resolve_answer(
            snap=snap,
            assistant_prior=assistant_prior,
            dialog=dialog,
            recovered_false_clarify=recovered_false_clarify,
        )
        if answered is not None:
            return answered

        if snap.kind == "clarify":
            return cls._finalize(
                task_kind="clarification_needed",
                requires_mcp=False,
                requires_user_choice=snap.requires_user_choice,
                underspec=snap.underspec,
                caps=(),
                continuation_kind=snap.kind,
                prior_context=assistant_prior,
                trust_prior_for_workers=False,
                reasoning=f"continuity=clarify; {snap.intent_reasoning}",
                confidence=snap.confidence,
                clarify_underspec_default=True,
            )

        return cls._finalize(
            task_kind=snap.raw_task,
            requires_mcp=snap.requires_mcp,
            requires_user_choice=snap.requires_user_choice,
            underspec=snap.underspec,
            caps=snap.caps,
            continuation_kind=snap.kind,
            prior_context=assistant_prior,
            trust_prior_for_workers=False,
            reasoning=f"continuity={snap.kind}; trust intent: {snap.intent_reasoning}",
            confidence=snap.confidence,
        )

    @classmethod
    def _try_resolve_format(
        cls,
        *,
        snap: _ResolveSnapshot,
        assistant_prior: str | None,
        dialog: DialogTurnWindow | None,
    ) -> EffectiveRoutingIntent | None:
        if snap.kind != "format":
            return None
        if assistant_prior is not None:
            prior = cls.resolve_worker_prior(
                assistant_prior=assistant_prior,
                dialog=dialog,
                continuation_kind=snap.kind,
                trust_prior_for_workers=True,
            )
            source = cls._prior_source_label(prior=prior, assistant_prior=assistant_prior)
            return cls._finalize(
                task_kind="response_formatting",
                requires_mcp=False,
                requires_user_choice=snap.requires_user_choice,
                underspec=snap.underspec,
                caps=("format",),
                continuation_kind=snap.kind,
                prior_context=prior,
                trust_prior_for_workers=True,
                reasoning=f"continuity=format; prior={source}; intent was {snap.raw_task}",
                confidence=snap.confidence,
            )
        user_prior = cls.prior_user_content(dialog)
        if user_prior is None:
            return None
        return cls._finalize(
            task_kind="response_formatting",
            requires_mcp=False,
            requires_user_choice=snap.requires_user_choice,
            underspec=snap.underspec,
            caps=("format",),
            continuation_kind=snap.kind,
            prior_context=user_prior,
            trust_prior_for_workers=True,
            reasoning=f"continuity=format; prior=user_payload; intent was {snap.raw_task}",
            confidence=snap.confidence,
        )

    @classmethod
    def _try_resolve_answer(
        cls,
        *,
        snap: _ResolveSnapshot,
        assistant_prior: str | None,
        dialog: DialogTurnWindow | None,
        recovered_false_clarify: bool,
    ) -> EffectiveRoutingIntent | None:
        # Answer continuity: enrich with prior; correct only history-blind false clarify.
        # Do NOT remapa social / capability / tool / workflow → knowledge_request.
        # (False social on real asks is Intent's job — Continuity cannot tell «как дела»
        # from «какой контекст» without phrase lists, 055.)
        # Do NOT remapa exclusive-choice menus into knowledge_request (unless slot filled).
        has_resolvable_prior = assistant_prior is not None or cls.prior_user_content(dialog, min_chars=1) is not None
        if not (snap.kind == "answer" and snap.refers_to_prior and has_resolvable_prior):
            return None
        task_kind, effective_caps, reasoning = _map_answer_task(
            snap=snap,
            recovered_false_clarify=recovered_false_clarify,
        )
        prior = cls.resolve_worker_prior(
            assistant_prior=assistant_prior,
            dialog=dialog,
            continuation_kind=snap.kind,
            trust_prior_for_workers=True,
        )
        source = cls._prior_source_label(prior=prior, assistant_prior=assistant_prior)
        return cls._finalize(
            task_kind=task_kind,
            requires_mcp=snap.requires_mcp,
            requires_user_choice=snap.requires_user_choice,
            underspec=snap.underspec,
            caps=effective_caps,
            continuation_kind=snap.kind,
            prior_context=prior,
            trust_prior_for_workers=True,
            reasoning=f"{reasoning}; prior={source}",
            confidence=snap.confidence,
        )


@dataclass
class _ResolveSnapshot:
    """Mutable working set for ContinuityPolicy.resolve (keeps resolve() shallow)."""

    kind: ContinuationKind
    refers_to_prior: bool
    raw_task: TaskKind
    requires_mcp: bool
    requires_user_choice: bool
    underspec: UnderspecificationKind
    caps: tuple[str, ...]
    intent_reasoning: str
    confidence: float
    choice_slot_filled: bool

    @classmethod
    def from_inputs(
        cls,
        *,
        contextualizer: ContextualizerOutput | None,
        raw_intent: IntentClassifierOutput | None,
    ) -> _ResolveSnapshot:
        return cls(
            kind=contextualizer.continuation_kind if contextualizer is not None else "new_topic",
            refers_to_prior=bool(contextualizer.refers_to_prior) if contextualizer is not None else False,
            raw_task=raw_intent.task_kind if raw_intent is not None else "clarification_needed",
            requires_mcp=raw_intent.requires_mcp if raw_intent is not None else False,
            requires_user_choice=bool(raw_intent.requires_user_choice) if raw_intent is not None else False,
            underspec=raw_intent.underspecification_kind if raw_intent is not None else "none",
            caps=raw_intent.candidate_capabilities if raw_intent is not None else (),
            intent_reasoning=raw_intent.reasoning if raw_intent is not None else "no intent",
            confidence=float(raw_intent.confidence) if raw_intent is not None else 1.0,
            choice_slot_filled=bool(contextualizer.choice_slot_filled) if contextualizer is not None else False,
        )


def _map_answer_task(
    *,
    snap: _ResolveSnapshot,
    recovered_false_clarify: bool,
) -> tuple[TaskKind, tuple[str, ...], str]:
    if snap.choice_slot_filled and snap.raw_task == "clarification_needed":
        caps = tuple(c for c in snap.caps if c != "user_choice") or ("summarize",)
        reasoning = f"continuity=answer; HITL choice slot filled → knowledge_request; {snap.intent_reasoning}"
        return "knowledge_request", caps, reasoning
    if (
        snap.raw_task == "clarification_needed"
        and not snap.requires_user_choice
        and snap.underspec != "discrete_choice"
    ):
        caps = snap.caps or ("summarize",)
        if recovered_false_clarify:
            reasoning = f"continuity=answer; recovered false clarify → knowledge_request; {snap.intent_reasoning}"
        else:
            reasoning = (
                f"continuity=answer; corrected history-blind clarify → knowledge_request; {snap.intent_reasoning}"
            )
        return "knowledge_request", caps, reasoning
    if recovered_false_clarify:
        reasoning = (
            f"continuity=answer; recovered false clarify; "
            f"trust intent task_kind={snap.raw_task}; {snap.intent_reasoning}"
        )
    else:
        reasoning = f"continuity=answer; trust intent task_kind={snap.raw_task}; {snap.intent_reasoning}"
    return snap.raw_task, snap.caps, reasoning
