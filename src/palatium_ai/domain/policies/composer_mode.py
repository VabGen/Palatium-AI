# src/palatium_ai/domain/policies/composer_mode.py

"""Map composer mode pills to Intent axis floors (055, Track P).

Pure policy: UI ``web_search`` / ``deep_think`` / ``agent`` never invent a task_kind.
They only raise floors Intent already owns (grounding, requires_mcp).
"""

from __future__ import annotations

from typing import Literal, cast

from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.policies.types import ComposerMode, ModelTier

_ComposerModeRaw = ComposerMode | str | None
_VALID_MODES: frozenset[str] = frozenset({"web_search", "deep_think", "agent"})


class ComposerModePolicy:
    """Apply explicit composer chrome to a classified intent (deterministic)."""

    @staticmethod
    def coerce(mode: _ComposerModeRaw) -> ComposerMode | None:
        if mode is None:
            return None
        value = str(mode).strip().lower()
        if value in _VALID_MODES:
            return cast("ComposerMode", value)
        return None

    @classmethod
    def apply(
        cls,
        output: IntentClassifierOutput | None,
        mode: _ComposerModeRaw,
    ) -> IntentClassifierOutput | None:
        """Raise grounding/MCP floors; leave task_kind / transformation untouched."""
        if output is None:
            return None
        resolved = cls.coerce(mode)
        if resolved is None:
            return output
        if resolved == "web_search":
            return output.model_copy(
                update={
                    "grounding": "required",
                    "grounding_reason": _merge_reason(output.grounding_reason, "composer_mode:web_search"),
                }
            )
        if resolved == "agent":
            return output.model_copy(
                update={
                    "requires_mcp": True,
                    "grounding_reason": _merge_reason(output.grounding_reason, "composer_mode:agent"),
                }
            )
        # deep_think: tier bump is ResearcherTierPolicy; keep grounding at least optional.
        grounding = output.grounding if output.grounding != "none" else "optional"
        return output.model_copy(
            update={
                "grounding": grounding,
                "grounding_reason": _merge_reason(output.grounding_reason, "composer_mode:deep_think"),
            }
        )

    @classmethod
    def researcher_tier_override(cls, mode: _ComposerModeRaw) -> ModelTier | None:
        """``deep_think`` → frontier/deep_reasoning tier; else no override."""
        if cls.coerce(mode) == "deep_think":
            return "deep_reasoning"
        return None


def _merge_reason(existing: str, addition: str) -> str:
    base = (existing or "").strip()
    if not base:
        return addition[:500]
    if addition in base:
        return base[:500]
    return f"{base}; {addition}"[:500]


ComposerModeName = Literal["web_search", "deep_think", "agent"]
