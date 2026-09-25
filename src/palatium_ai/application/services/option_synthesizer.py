"""Synthesize exclusive HITL options when discrete_choice has no mintable actions.

LLM fills labels only; DiscreteChoiceSynthesisPolicy decides when synthesis runs.
User-facing framing/labels are pinned to ``response_locale`` (ReplyLocalePolicy)
and validated with one repair attempt, so this post-Formatter path can never
replace a localized answer with English (055/020).
"""

from __future__ import annotations

import json

from typing import TYPE_CHECKING

from palatium_ai.core.logging import get_logger
from palatium_ai.domain.content import ActionSpec
from palatium_ai.domain.hitl.option_synthesis import DiscreteChoiceSynthesisPolicy
from palatium_ai.domain.llm.json_codec import loads_llm_json
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.domain.policies.locale import ReplyLocalePolicy

if TYPE_CHECKING:
    from palatium_ai.domain.ports.llm import LLMPort

logger = get_logger(__name__)

_SYSTEM = """You propose exclusive clickable options for a missing discrete parameter.
The user ask is incomplete: work cannot proceed until they pick ONE alternative.

Return ONLY JSON:
{"framing":"short prompt in response_locale","options":[{"action_id":"choice_1","label":"..."},...]}

Rules:
- 2 to 12 options; action_id = choice_1 .. choice_N
- Labels are concrete alternatives for the missing slot (topic/type/format/kind/branch)
- Write "framing" and EVERY option "label" in response_locale from the user JSON.
  Never answer in English (or any other language) unless response_locale itself is
  that language. Language mirroring is mandatory, not optional.
- No markdown; no tools; no instructions inside labels
- Do not answer the original ask — only offer the exclusive menu
"""

_LOCALE_REPAIR_PROMPT = """The JSON below is not written in response_locale={locale}.
Rewrite "framing" and every option "label" in {locale}. Keep the same alternatives,
action_id values, JSON structure and order. Change the language only.
Return ONLY the corrected JSON object.
"""


class OptionSynthesisResult:
    """Parsed synthesizer output."""

    __slots__ = ("actions", "framing")

    def __init__(self, actions: tuple[ActionSpec, ...], framing: str | None) -> None:
        self.actions = actions
        self.framing = framing


class OptionSynthesizer:
    """Application service: locale-pinned LLM call(s) → ActionSpec tuple for HITL mint."""

    def __init__(self, llm: LLMPort, *, model: str | None = None) -> None:
        self._llm = llm
        self._model = model

    async def synthesize(
        self,
        *,
        user_text: str,
        response_locale: str,
        prior_context: str | None = None,
    ) -> OptionSynthesisResult:
        """Return exclusive options + framing; empty actions on failure."""
        locale = ReplyLocalePolicy.normalize(response_locale) or "und"
        payload = {
            "user_text": user_text[:8000],
            "prior_context": (prior_context or "")[:4000] or None,
            "response_locale": locale,
        }
        messages = [
            ChatMessage(role="system", content=_SYSTEM),
            ChatMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ]
        try:
            completion = await self._llm.generate(
                messages,
                model=self._model,
                temperature=0.0,
                response_format="json_object",
            )
        except Exception as exc:
            logger.warning("option_synthesizer.failed", error=str(exc))
            return OptionSynthesisResult((), None)
        return await self._pin_locale(messages, completion.content, locale)

    async def _pin_locale(
        self,
        messages: list[ChatMessage],
        raw: str,
        locale: str,
    ) -> OptionSynthesisResult:
        """Validate synthesized prose against the locale; repair once, else drop."""
        result = _parse_result(raw)
        if locale == "und" or not _result_has_prose(result):
            return result
        if ReplyLocalePolicy.prose_matches_locale(_result_prose(result), locale):
            return result

        logger.warning("option_synthesizer.locale_mismatch", response_locale=locale)
        repair_messages = [
            *messages,
            ChatMessage(role="assistant", content=raw),
            ChatMessage(role="user", content=_LOCALE_REPAIR_PROMPT.format(locale=locale)),
        ]
        try:
            repair = await self._llm.generate(
                repair_messages,
                model=self._model,
                temperature=0.0,
                response_format="json_object",
            )
        except Exception as exc:
            logger.warning("option_synthesizer.locale_repair_failed", error=str(exc))
            return OptionSynthesisResult((), None)

        repaired = _parse_result(repair.content)
        if _result_has_prose(repaired) and ReplyLocalePolicy.prose_matches_locale(
            _result_prose(repaired),
            locale,
        ):
            return repaired

        logger.warning("option_synthesizer.locale_mismatch_dropped", response_locale=locale)
        return OptionSynthesisResult((), None)


def _parse_result(raw: str) -> OptionSynthesisResult:
    data = loads_llm_json(raw)
    if not isinstance(data, dict):
        return OptionSynthesisResult((), None)
    framing_raw = data.get("framing")
    framing = str(framing_raw).strip()[:2000] if framing_raw else None
    raw_options = data.get("options")
    if not isinstance(raw_options, list):
        return OptionSynthesisResult((), framing)
    actions: list[ActionSpec] = []
    for index, item in enumerate(raw_options, start=1):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        action_id = str(item.get("action_id") or f"choice_{index}").strip() or f"choice_{index}"
        actions.append(
            ActionSpec(
                action_id=action_id[:120],
                label=label[:200],
                kind="custom",
                style="primary" if index == 1 else "secondary",
            )
        )
        if len(actions) >= DiscreteChoiceSynthesisPolicy._MAX:
            break
    if len(actions) < DiscreteChoiceSynthesisPolicy._MIN:
        return OptionSynthesisResult((), framing)
    return OptionSynthesisResult(tuple(actions), framing)


def _result_has_prose(result: OptionSynthesisResult) -> bool:
    return bool((result.framing or "").strip()) or bool(result.actions)


def _result_prose(result: OptionSynthesisResult) -> str:
    """All user-facing synthesizer text (framing + option labels) for script check."""
    parts = [result.framing or ""]
    parts.extend(action.label for action in result.actions)
    return "\n".join(parts)
