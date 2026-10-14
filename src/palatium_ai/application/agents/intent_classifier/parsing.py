# src/palatium_ai/application/agents/intent_classifier/parsing.py

"""Deterministic parsing for IntentClassifier LLM JSON output."""

from __future__ import annotations

from typing import cast

from palatium_ai.domain.agents.intent import IntentClassifierOutput, TaskKind, UnderspecificationKind
from palatium_ai.domain.agents.user_choice_intent import UserChoiceIntentPolicy
from palatium_ai.domain.llm.json_codec import loads_llm_json
from palatium_ai.domain.policies.grounding import GroundingPolicy
from palatium_ai.domain.policies.types import GroundingMode

_VALID_TASK_KINDS: frozenset[str] = frozenset(
    {
        "capability_discovery",
        "knowledge_request",
        "multi_step_workflow",
        "tool_execution",
        "response_formatting",
        "social_conversation",
        "clarification_needed",
    },
)

_VALID_UNDERSPEC: frozenset[str] = frozenset({"none", "open_text", "discrete_choice"})


def parse_classifier_output(raw_content: str) -> IntentClassifierOutput:
    """Parse JSON LLM response into IntentClassifierOutput."""
    payload = loads_llm_json(raw_content)
    if not isinstance(payload, dict):
        msg = "Intent classifier JSON must be an object"
        raise ValueError(msg)
    task_kind = _coerce_task_kind(payload.get("task_kind"))
    requires_mcp = bool(payload.get("requires_mcp", False))
    if task_kind == "social_conversation":
        requires_mcp = False
    raw_capabilities = payload.get("candidate_capabilities", [])
    capabilities: tuple[str, ...] = (
        tuple(str(item) for item in raw_capabilities if str(item)) if isinstance(raw_capabilities, list) else ()
    )
    grounding = _coerce_grounding(payload.get("grounding"), task_kind=task_kind, capabilities=capabilities)
    grounding_reason = str(payload.get("grounding_reason") or payload.get("reason") or "")[:500]

    return UserChoiceIntentPolicy.normalize(
        IntentClassifierOutput(
            task_kind=task_kind,
            requires_mcp=requires_mcp,
            requires_user_choice=_coerce_bool_flag(payload.get("requires_user_choice")),
            underspecification_kind=_coerce_underspecification_kind(payload),
            candidate_capabilities=capabilities,
            grounding=grounding,
            grounding_reason=grounding_reason,
            confidence=float(payload.get("confidence", 0.0)),
            reasoning=str(payload.get("reasoning", "No reasoning provided")),
        ),
    )


def _coerce_bool_flag(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes"}
    return False


def _coerce_underspecification_kind(payload: dict[str, object]) -> UnderspecificationKind:
    raw = payload.get("underspecification_kind")
    if isinstance(raw, str) and raw.strip() in _VALID_UNDERSPEC:
        return cast("UnderspecificationKind", raw.strip())
    return "none"


def _coerce_task_kind(value: object) -> TaskKind:
    """Unknown labels take the default answer path — never a clarification (055)."""
    if isinstance(value, str) and value.strip() in _VALID_TASK_KINDS:
        return cast("TaskKind", value.strip())
    return "knowledge_request"


def _coerce_grounding(
    value: object,
    *,
    task_kind: TaskKind,
    capabilities: tuple[str, ...],
) -> GroundingMode:
    """Invalid/missing → optional. Soft defaults for social/compose when omitted."""
    mode = GroundingPolicy.coerce_mode(value)
    if isinstance(value, str) and value.strip() in {"required", "optional", "none"}:
        return mode
    if task_kind == "social_conversation":
        return "none"
    caps = {c.strip().lower() for c in capabilities if c.strip()}
    if "compose" in caps:
        return "none"
    return mode
