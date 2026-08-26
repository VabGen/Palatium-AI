"""Synthesize exclusive HITL options when discrete_choice has no mintable actions.

LLM fills labels only; DiscreteChoiceSynthesisPolicy decides when synthesis runs.
"""

from __future__ import annotations

import json

from typing import TYPE_CHECKING

from palatium_ai.core.logging import get_logger
from palatium_ai.domain.content import ActionSpec
from palatium_ai.domain.hitl.option_synthesis import DiscreteChoiceSynthesisPolicy
from palatium_ai.domain.llm.json_codec import loads_llm_json
from palatium_ai.domain.llm.models import ChatMessage

if TYPE_CHECKING:
    from palatium_ai.domain.ports.llm import LLMPort

logger = get_logger(__name__)

_SYSTEM = """You propose exclusive clickable options for a missing discrete parameter.
The user ask is incomplete: work cannot proceed until they pick ONE alternative.

Return ONLY JSON:
{"framing":"short prompt in the user's language","options":[{"action_id":"choice_1","label":"..."},...]}

Rules:
- 2 to 12 options; action_id = choice_1 .. choice_N
- Labels are concrete alternatives for the missing slot (topic/type/format/kind/branch)
- Match the user language; no markdown; no tools; no instructions inside labels
- Do not answer the original ask — only offer the exclusive menu
"""


class OptionSynthesisResult:
    """Parsed synthesizer output."""

    __slots__ = ("actions", "framing")

    def __init__(self, actions: tuple[ActionSpec, ...], framing: str | None) -> None:
        self.actions = actions
        self.framing = framing


class OptionSynthesizer:
    """Application service: one LLM call → ActionSpec tuple for HITL mint."""

    def __init__(self, llm: LLMPort, *, model: str | None = None) -> None:
        self._llm = llm
        self._model = model

    async def synthesize(
        self,
        *,
        user_text: str,
        prior_context: str | None = None,
    ) -> OptionSynthesisResult:
        """Return exclusive options + framing; empty actions on failure."""
        payload = {
            "user_text": user_text[:8000],
            "prior_context": (prior_context or "")[:4000] or None,
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
            return _parse_result(completion.content)
        except Exception as exc:
            logger.warning("option_synthesizer.failed", error=str(exc))
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
