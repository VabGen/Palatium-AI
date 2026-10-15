# src/palatium_ai/domain/policies/transform.py

"""How a format-continuation should transform prior content (055).

``continuation_kind=format`` only says the ask depends on prior. This axis says
*how*: layout-only restructure vs content rewrite (expand / shorten / rewrite).
ExecutionPlanner + Continuity map restructure → ``format_only``; content
transforms → ``reason_only`` over trusted prior (not Formatter brand template).
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.types import (
    TRANSFORMATION_DEFAULT,
    TransformationKind,
)

_CONTENT_TRANSFORM: Final[frozenset[str]] = frozenset({"expand", "shorten", "rewrite"})
_VALID: Final[frozenset[str]] = frozenset({"none", "restructure", "expand", "shorten", "rewrite"})

_CAPABILITY_FOR: Final[dict[TransformationKind, str]] = {
    "expand": "expand",
    "shorten": "shorten",
    "rewrite": "rewrite",
    "restructure": "format",
    "none": "format",
}


class TransformRouteDecision(BaseModel):
    """Whether a format-continuation may stay on Formatter ``format_only``."""

    model_config = {"frozen": True}

    format_only: bool
    reason: str = Field(min_length=1, max_length=128)


class TransformPolicy:
    """Pure domain policy for the transformation axis."""

    @classmethod
    def coerce(cls, raw: object) -> TransformationKind:
        if isinstance(raw, str) and raw.strip() in _VALID:
            return raw.strip()  # type: ignore[return-value]
        return TRANSFORMATION_DEFAULT

    @classmethod
    def needs_reason_over_prior(cls, transformation: TransformationKind | str | None) -> bool:
        """Expand / shorten / rewrite need LLM reasoning over prior, not layout pass."""
        return cls.coerce(transformation) in _CONTENT_TRANSFORM

    @classmethod
    def decide_format_route(
        cls,
        *,
        transformation: TransformationKind | str | None,
    ) -> TransformRouteDecision:
        """restructure/none → Formatter; content transforms → Researcher reason_only."""
        kind = cls.coerce(transformation)
        if kind in _CONTENT_TRANSFORM:
            return TransformRouteDecision(
                format_only=False,
                reason=f"transform_{kind}_needs_reason",
            )
        return TransformRouteDecision(
            format_only=True,
            reason=f"transform_{kind}_format_only",
        )

    @classmethod
    def merge_capability(
        cls,
        caps: tuple[str, ...],
        transformation: TransformationKind | str | None,
    ) -> tuple[str, ...]:
        """Ensure candidate_capabilities carry the transform tag for Researcher prompts."""
        kind = cls.coerce(transformation)
        tag = _CAPABILITY_FOR[kind]
        if not tag:
            return caps
        lowered = {c.strip().lower() for c in caps if c.strip()}
        if tag in lowered:
            return caps
        return (*caps, tag)
