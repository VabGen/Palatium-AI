# src/palatium_ai/domain/policies/grounding.py

"""Adaptive grounding decisions (Retrieve-Check-Route, 055).

Pure policy: grounding mode + empty retrieval → degrade / clarify / stub.
Feature flag lives in ObservabilityConfig; callers pass ``enabled``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.types import GROUNDING_DEFAULT, GroundingMode

GroundingEmptyAction = Literal["stub", "degrade_reason", "clarify"]


class GroundingEmptyDecision(BaseModel):
    """How Researcher should handle empty MCP retrieval."""

    model_config = {"frozen": True}

    action: GroundingEmptyAction
    reason: str = Field(min_length=1, max_length=128)


_CLARIFY_QUERY_MAX = 120


class GroundingPolicy:
    """Pure domain policy for adaptive grounding routing."""

    @classmethod
    def coerce_mode(cls, raw: object) -> GroundingMode:
        if isinstance(raw, str) and raw.strip() in {"required", "optional", "none"}:
            return raw.strip()  # type: ignore[return-value]
        return GROUNDING_DEFAULT

    @classmethod
    def decide_empty_retrieval(
        cls,
        *,
        enabled: bool,
        grounding: GroundingMode | str | None,
    ) -> GroundingEmptyDecision:
        """Empty search_knowledge outcome when Adaptive Grounding is on/off."""
        if not enabled:
            return GroundingEmptyDecision(action="stub", reason="adaptive_grounding_off")
        mode = cls.coerce_mode(grounding)
        if mode == "required":
            return GroundingEmptyDecision(action="clarify", reason="grounding_required_empty")
        if mode == "none":
            # Planner should not have retrieved; if it did, still answer from knowledge.
            return GroundingEmptyDecision(action="degrade_reason", reason="grounding_none_empty")
        return GroundingEmptyDecision(action="degrade_reason", reason="grounding_optional_empty")

    @classmethod
    def required_empty_clarification(cls, user_text: str | None) -> str:
        """Query-aware clarification when required grounding has no retrieval hits."""
        snippet = " ".join((user_text or "").split())
        if len(snippet) > _CLARIFY_QUERY_MAX:
            snippet = f"{snippet[: _CLARIFY_QUERY_MAX - 1]}…"
        if snippet:
            return (
                f"По запросу «{snippet}» в доступных источниках ничего не найдено. "
                "Для ответа нужны ваши данные — уточните источник "
                "(файл, документ, период) или приложите файл."
            )
        return (
            "Для ответа нужны ваши данные (файл, документ или запись), которых сейчас нет. "
            "Уточните источник или приложите файл."
        )
