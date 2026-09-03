# src/palatium_ai/application/agents/researcher/parsing.py

"""Decode Researcher AgentInput and parse LLM/MCP outputs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.application.agents.researcher.config import SUMMARY_MAX_CHARS
from palatium_ai.core.logging.redact import redact_text
from palatium_ai.domain.agents.researcher import ResearcherInput, ResearcherOutput
from palatium_ai.domain.llm.json_codec import loads_llm_json
from palatium_ai.domain.memory.tool_output import (
    compress_worker_context,
    wrap_untrusted_tool_output,
)

if TYPE_CHECKING:
    from palatium_ai.application.tools.mcp import MCPToolCallOutcome

FAILURE_PLACEHOLDER_SUMMARY = "(no output)"


def decode_researcher_input(input_context: dict[str, str]) -> ResearcherInput:
    from palatium_ai.domain.agents.context_packet import ContextPacket

    packet = ContextPacket.model_validate_json(input_context["context_packet_json"])
    prior = input_context.get("prior_context", "").strip()
    revision = input_context.get("revision_feedback", "").strip()
    return ResearcherInput(
        task_id=input_context["_task_id"],
        context_packet=packet,
        prior_context=prior or None,
        mcp_tool_output_max_chars=int(input_context.get("mcp_tool_output_max_chars", "3000")),
        revision_feedback=revision or None,
    )


def parse_researcher_output(raw_content: str) -> ResearcherOutput:
    """Parse LLM JSON into ResearcherOutput with hardening against malformed values."""
    payload = loads_llm_json(raw_content)
    if not isinstance(payload, dict):
        raise ValueError("Researcher JSON must be an object")

    raw_summary = payload.get("summary", "No summary provided")
    summary = str(raw_summary).strip() or "No summary provided"
    if len(summary) > SUMMARY_MAX_CHARS:
        summary = summary[:SUMMARY_MAX_CHARS].rstrip() + "…"

    try:
        confidence = float(payload.get("confidence", 0.0))
    except TypeError, ValueError:
        confidence = 0.0
    if confidence != confidence or confidence in (float("inf"), float("-inf")):
        confidence = 0.0
    confidence = min(max(confidence, 0.0), 1.0)

    raw_sources = payload.get("sources_used", [])
    sources = tuple(str(item) for item in raw_sources)[:10] if isinstance(raw_sources, list) else ()

    return ResearcherOutput(
        summary=summary,
        confidence=confidence,
        sources_used=sources,
    )


def approval_granted(decision: object) -> bool:
    """Interpret LangGraph resume payload from HITL approve/reject."""
    if isinstance(decision, dict):
        action = decision.get("action_id") or decision.get("action")
        return action in {"approve", "approved", "allow"}
    if isinstance(decision, str):
        return decision.strip().lower() in {"approve", "approved", "allow"}
    return False


def redact_mcp_arguments(arguments: dict[str, object]) -> dict[str, object]:
    """Redact secret-shaped substrings before checkpoint/HITL interrupt payload."""
    redacted: dict[str, object] = {}
    for key, value in arguments.items():
        if isinstance(value, str):
            redacted[key] = redact_text(value)
        else:
            redacted[key] = value
    return redacted


def summarize_mcp_content(
    outcome: MCPToolCallOutcome,
    *,
    max_chars: int,
    server_name: str,
    tool_name: str,
) -> str:
    """Convert MCP tool content into budgeted untrusted text for downstream LLM."""
    parts: list[str] = []
    for item in outcome.content:
        text = item.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    raw = "\n".join(parts) if parts else "MCP tool returned no text content."
    raw = redact_text(raw)
    fenced = wrap_untrusted_tool_output(raw, source=f"mcp:{server_name}.{tool_name}")
    return compress_worker_context(fenced, max_chars=max_chars, label="mcp")
