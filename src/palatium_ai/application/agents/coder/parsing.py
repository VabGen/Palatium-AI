# src/palatium_ai/application/agents/coder/parsing.py

"""Coder parse helpers."""

from __future__ import annotations

import json

from typing import Any
from uuid import UUID

from palatium_ai.core.types.coerce import coerce_float
from palatium_ai.domain.agents.coder import CoderInput, CoderOutput
from palatium_ai.domain.agents.context_packet import ContextPacket


def decode_coder_input(context: dict[str, str]) -> CoderInput:
    packet = ContextPacket.model_validate_json(context["context_packet_json"])
    task_id = context.get("_task_id") or packet.task_id
    feedback = (context.get("revision_feedback") or "").strip() or None
    return CoderInput(task_id=task_id, context_packet=packet, revision_feedback=feedback)


def parse_coder_output(raw: str) -> CoderOutput:
    payload: Any = json.loads(raw)
    if not isinstance(payload, dict):
        msg = "coder output must be a JSON object"
        raise ValueError(msg)
    summary = str(payload.get("summary", "")).strip()
    if not summary:
        msg = "coder summary is required"
        raise ValueError(msg)
    return CoderOutput(
        summary=summary,
        confidence=coerce_float(payload.get("confidence", 0.0)),
        language=str(payload.get("language", "")).strip()[:32],
        requires_sandbox_exec=bool(payload.get("requires_sandbox_exec", False)),
    )


def task_id_uuid(task_id: str) -> UUID:
    try:
        return UUID(task_id)
    except ValueError:
        return UUID(int=0)
