"""Contextualizer runtime flags."""

from __future__ import annotations

from pydantic import Field

from .base import BaseConfig


class ContextualizerConfig(BaseConfig):
    """Debug/diagnostic switches for the Contextualizer (continuation) agent.

    Production turns keep this off: payloads may contain user dialog content.
    """

    debug_payload: bool = Field(
        default=False,
        validation_alias="CONTEXTUALIZER_DEBUG_PAYLOAD",
        description=(
            "When true, ContextualizerAgent logs gate reason, LLM user_payload, "
            "and parsed continuation fields. Leave false in production."
        ),
    )
