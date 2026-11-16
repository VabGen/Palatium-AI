# src/palatium_ai/domain/policies/reasoning_effort.py

"""Map model tier → default reasoning_effort (independent of verbosity, 055)."""

from __future__ import annotations

from typing import Final

from palatium_ai.core.types.model_registry import abstract_tier_for
from palatium_ai.domain.llm.controls import ReasoningEffort

#: Abstract tier → default effort. deep_reasoning collapses to frontier→high;
#: ``max`` stays opt-in (Opus-only on Anthropic) via AgentConfig override.
_EFFORT_BY_ABSTRACT: Final[dict[str, ReasoningEffort]] = {
    "fast": "low",
    "standard": "medium",
    "frontier": "high",
}

_DEFAULT: Final[ReasoningEffort] = "medium"


class ReasoningEffortPolicy:
    """Pure domain policy: runtime model_tier → reasoning_effort dial."""

    @classmethod
    def for_model_tier(cls, model_tier: str | None) -> ReasoningEffort:
        if not model_tier:
            return _DEFAULT
        return _EFFORT_BY_ABSTRACT.get(abstract_tier_for(model_tier), _DEFAULT)
