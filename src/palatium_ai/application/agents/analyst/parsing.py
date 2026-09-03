# src/palatium_ai/application/agents/analyst/parsing.py

"""Analyst parse helpers."""

from __future__ import annotations

import json

from typing import Any

from palatium_ai.core.types.coerce import coerce_float
from palatium_ai.domain.agents.analyst import AnalystInput, AnalystOutput
from palatium_ai.domain.agents.context_packet import ContextPacket


def decode_analyst_input(context: dict[str, str]) -> AnalystInput:
    packet = ContextPacket.model_validate_json(context["context_packet_json"])
    task_id = context.get("_task_id") or packet.task_id
    feedback = (context.get("revision_feedback") or "").strip() or None
    return AnalystInput(task_id=task_id, context_packet=packet, revision_feedback=feedback)


def parse_analyst_output(raw: str) -> AnalystOutput:
    payload: Any = json.loads(raw)
    if not isinstance(payload, dict):
        msg = "analyst output must be a JSON object"
        raise ValueError(msg)
    summary = str(payload.get("summary", "")).strip()
    if not summary:
        msg = "analyst summary is required"
        raise ValueError(msg)
    findings_raw = payload.get("findings", ())
    findings: tuple[str, ...] = ()
    if isinstance(findings_raw, list):
        findings = tuple(str(item).strip() for item in findings_raw if str(item).strip())
    return AnalystOutput(
        summary=summary,
        confidence=coerce_float(payload.get("confidence", 0.0)),
        findings=findings,
    )
