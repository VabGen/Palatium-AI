# src/palatium_ai/domain/policies/verbosity.py

"""Length axis of a user-facing answer (W7, 055).

The user asks for brevity or depth in words ("сократи", "подробнее"), not through a
dedicated request field. The only server-side signal that survives classification is the
transformation axis: ``shorten``/``expand`` already mean "make this text shorter/longer".
So the budget is *derived*, never self-declared by the model — a document that could
choose "minimal" for itself would be marking its own homework (050).

The policy is pure and deterministic: same transformation → same budget, no I/O, so the
payload builder and ``align_formatter_meta`` cannot disagree.

API mapping (wired through ``LLMPort`` → LiteLLM ``verbosity``):
``minimal→low``, ``standard→medium``, ``detailed→high``. Reasoning depth is a
*separate* dial — see ``ReasoningEffortPolicy`` / ``reasoning_effort``.

Anthropic (and other non-``_VERBOSITY_CAPABLE`` providers) do not receive this API
dial: the adapter drops it and logs ``llm.verbosity.dropped``; answer length on
those paths is still steered by the transformation/prompt contract.
"""

from __future__ import annotations

from typing import Final

from palatium_ai.domain.content.content_document import VerbosityBudget
from palatium_ai.domain.llm.controls import TextVerbosity
from palatium_ai.domain.policies.transform import TransformPolicy
from palatium_ai.domain.policies.types import TransformationKind

BUDGET_DEFAULT: Final[VerbosityBudget] = "standard"

# Only the two length-bearing transformations move the axis. ``rewrite`` and
# ``restructure`` change wording/layout at the same length, so they stay standard.
_BUDGET_FOR: Final[dict[TransformationKind, VerbosityBudget]] = {
    "shorten": "minimal",
    "expand": "detailed",
}

_API_VERBOSITY: Final[dict[VerbosityBudget, TextVerbosity]] = {
    "minimal": "low",
    "standard": "medium",
    "detailed": "high",
}


class VerbosityPolicy:
    """Pure domain policy: transformation axis → answer length budget → API verbosity."""

    @classmethod
    def for_transformation(cls, transformation: TransformationKind | str | None) -> VerbosityBudget:
        return _BUDGET_FOR.get(TransformPolicy.coerce(transformation), BUDGET_DEFAULT)

    @classmethod
    def to_api_verbosity(cls, budget: VerbosityBudget | str | None) -> TextVerbosity:
        """Map product budget onto OpenAI/LiteLLM ``verbosity`` (length only)."""
        if budget in _API_VERBOSITY:
            return _API_VERBOSITY[budget]
        return _API_VERBOSITY[BUDGET_DEFAULT]
