# src/palatium_ai/application/agents/context_enricher/weaving/parsing.py

"""Decode weaving-phase AgentInput context."""

from __future__ import annotations

import json

from palatium_ai.domain.agents.context_weaver import ContextWeaverInput


def decode_context_weaver_input(input_context: dict[str, str], *, instruction: str) -> ContextWeaverInput:
    caps_raw = json.loads(input_context.get("candidate_capabilities_json", "[]"))
    capabilities = tuple(str(item) for item in caps_raw)
    return ContextWeaverInput(
        task_id=input_context["_task_id"],
        user_text=instruction,
        task_kind=input_context["task_kind"],  # type: ignore[arg-type]
        route=input_context["route"],  # type: ignore[arg-type]
        route_plan=input_context["route_plan"],
        requires_mcp=input_context.get("requires_mcp", "false").lower() == "true",
        candidate_capabilities=capabilities,
    )
