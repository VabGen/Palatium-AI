# src/palatium_ai/domain/policies/types.py

"""Единый реестр осей и Literal-типов политик (055, 000)."""

from __future__ import annotations

from typing import Literal

# --- Agent registry (000, 030) ---

AgentRole = Literal[
    "intent_classifier",
    "supervisor",
    "researcher",
    "critic",
    "formatter",
    "memory_keeper",
    "context_enricher",
    "text_ingestor",
    "coder",
    "analyst",
]

# Runtime tier names; abstract frontier|standard|fast mapping — Wave 3 (core/config/llm).
ModelTier = Literal["nano", "small", "mid", "frontier", "deep_reasoning"]

# --- Intent / continuity (context_enricher + intent_classifier) ---

TaskKind = Literal[
    "capability_discovery",
    "knowledge_request",
    "multi_step_workflow",
    "tool_execution",
    "response_formatting",
    "social_conversation",
    "clarification_needed",
]

UnderspecificationKind = Literal[
    "none",
    "open_text",
    "discrete_choice",
]

ContinuationKind = Literal["format", "answer", "new_topic", "clarify"]

# Need for external retrieval (orthogonal to task_kind). Intent classifies;
# ExecutionPlanner maps to retrieve_then_reason vs reason_only (Adaptive RAG).
GroundingMode = Literal["required", "optional", "none"]
GROUNDING_DEFAULT: GroundingMode = "optional"

# Structural length floor: user turn long enough to be a document/payload vs
# phatic ping. Shared by Continuity + Critic (055 — one constant, not copies).
SUBSTANTIVE_USER_PAYLOAD_CHARS = 400

# Intent ``candidate_capabilities`` tags for generation asks. Generation stays a
# ``knowledge_request`` (no new TaskKind): planner sends ``compose`` to reason_only
# (``draft`` keeps retrieval), Formatter keeps the generated text's own shape.
CONTENT_GENERATION_CAPABILITY = "compose"
DOCUMENT_GENERATION_CAPABILITY = "draft"
# Exact body of a file/tool payload (OCR, extract, "дай текст"). No second paraphrase.
VERBATIM_EXTRACTION_CAPABILITY = "verbatim_extraction"

# --- Routing / execution (supervisor, researcher, critic) ---

ExecutionStrategy = Literal[
    "direct_tool_call",
    "retrieve_then_reason",
    "reason_only",
    "code_sandbox",
    "data_analysis",
    "format_only",
    "ack_only",
    "clarify",
]

type RouteStrategy = ExecutionStrategy

# L1 response-cache allow-list only. Graph Critic skip is decided in
# ``route_after_context`` (social also uses ``format_only`` — must not inherit skip).
# ``ack_only`` is eval/cassette-only; live social is ``format_only`` + Formatter LLM.
LOW_RISK_ROUTE_STRATEGIES: frozenset[RouteStrategy] = frozenset(
    {"format_only"},
)

# --- Untrusted content (attachments, MCP/tool output) ---

# How a payload with detected injection signals may be used. ``allow`` keeps it
# verbatim, ``mask`` redacts the matched spans, ``quarantine``/``reject`` let
# nothing reach the prompt and require human review (020, OWASP LLM01).
UntrustedContentAction = Literal["allow", "mask", "quarantine", "reject"]

__all__ = [
    "CONTENT_GENERATION_CAPABILITY",
    "DOCUMENT_GENERATION_CAPABILITY",
    "GROUNDING_DEFAULT",
    "LOW_RISK_ROUTE_STRATEGIES",
    "SUBSTANTIVE_USER_PAYLOAD_CHARS",
    "VERBATIM_EXTRACTION_CAPABILITY",
    "AgentRole",
    "ContinuationKind",
    "ExecutionStrategy",
    "GroundingMode",
    "ModelTier",
    "RouteStrategy",
    "TaskKind",
    "UnderspecificationKind",
    "UntrustedContentAction",
]
