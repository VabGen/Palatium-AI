"""response_shape axis — Intent parsing, Continuity pass-through, packet default."""

from __future__ import annotations

import json

from palatium_ai.application.agents.intent_classifier.parsing import parse_classifier_output
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.policies import ContinuityPolicy


def _payload(**overrides: object) -> str:
    base: dict[str, object] = {
        "task_kind": "knowledge_request",
        "requires_mcp": False,
        "requires_user_choice": False,
        "underspecification_kind": "none",
        "candidate_capabilities": ["compare"],
        "grounding": "optional",
        "grounding_reason": "user asks to compare uploads",
        "transformation": "none",
        "file_reference": "none",
        "confidence": 0.9,
        "reasoning": "explicit comparison",
    }
    base.update(overrides)
    return json.dumps(base, ensure_ascii=False)


def test_parser_keeps_valid_shape() -> None:
    parsed = parse_classifier_output(_payload(response_shape="comparison_table"))
    assert parsed.response_shape == "comparison_table"


def test_parser_defaults_missing_or_unknown_shape_to_auto() -> None:
    assert parse_classifier_output(_payload()).response_shape == "auto"
    assert parse_classifier_output(_payload(response_shape="fancy_chart")).response_shape == "auto"
    assert parse_classifier_output(_payload(response_shape=None)).response_shape == "auto"


def test_continuity_passes_requested_shape_without_remapping() -> None:
    raw = IntentClassifierOutput(
        task_kind="knowledge_request",
        requires_mcp=False,
        candidate_capabilities=("plan",),
        grounding="optional",
        response_shape="plan",
        confidence=0.9,
        reasoning="user asked for steps",
    )
    effective = ContinuityPolicy.resolve(contextualizer=None, dialog=None, raw_intent=raw)
    assert effective.task_kind == "knowledge_request"
    assert effective.response_shape == "plan"


def test_continuity_defaults_to_auto_without_intent() -> None:
    effective = ContinuityPolicy.resolve(contextualizer=None, dialog=None, raw_intent=None)
    assert effective.response_shape == "auto"


def test_context_packet_defaults_to_auto() -> None:
    packet = ContextPacket(
        task_id="t1",
        user_text="привет",
        task_kind="social_conversation",
        route="formatter",
        route_plan="format_only",
        requires_mcp=False,
        execution_plan=ToolExecutionPlan(
            strategy="format_only",
            requires_tool_call=False,
            rationale="test packet",
        ),
        context_summary="n/a",
    )
    assert packet.response_shape == "auto"
