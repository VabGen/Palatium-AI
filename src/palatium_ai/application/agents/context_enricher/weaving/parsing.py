# src/palatium_ai/application/agents/context_enricher/weaving/parsing.py

"""Decode weaving-phase AgentInput context."""

from __future__ import annotations

import json

from palatium_ai.domain.agents.context_weaver import ContextWeaverInput
from palatium_ai.domain.policies.grounding import GroundingPolicy
from palatium_ai.domain.policies.types import FILE_REFERENCE_DEFAULT


def decode_context_weaver_input(input_context: dict[str, str], *, instruction: str) -> ContextWeaverInput:
    caps_raw = json.loads(input_context.get("candidate_capabilities_json", "[]"))
    capabilities = tuple(str(item) for item in caps_raw)
    return ContextWeaverInput(
        task_id=input_context["_task_id"],
        user_text=instruction,
        task_kind=input_context["task_kind"],  # type: ignore[arg-type]  # context собран из Literal-реестра (017)
        route=input_context["route"],  # type: ignore[arg-type]  # context собран из Literal-реестра (017)
        route_plan=input_context["route_plan"],
        requires_mcp=input_context.get("requires_mcp", "false").lower() == "true",
        candidate_capabilities=capabilities,
        grounding=GroundingPolicy.coerce_mode(input_context.get("grounding")),
        grounding_reason=(input_context.get("grounding_reason") or "")[:500],
        has_attachment_context=input_context.get("has_attachment_context", "false").lower() == "true",
        has_trusted_prior=input_context.get("has_trusted_prior", "false").lower() == "true",
        file_reference=input_context.get("file_reference") or FILE_REFERENCE_DEFAULT,  # type: ignore[arg-type]  # Literal registry (017)
    )
