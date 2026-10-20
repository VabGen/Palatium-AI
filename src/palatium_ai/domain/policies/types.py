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

# How a format-continuation transforms prior (orthogonal to continuation_kind).
# restructure → Formatter format_only; expand/shorten/rewrite → Researcher reason_only.
TransformationKind = Literal["none", "restructure", "expand", "shorten", "rewrite"]
TRANSFORMATION_DEFAULT: TransformationKind = "none"

# Need for external retrieval (orthogonal to task_kind). Intent classifies;
# ExecutionPlanner maps to retrieve_then_reason vs reason_only (Adaptive RAG).
GroundingMode = Literal["required", "optional", "none"]
GROUNDING_DEFAULT: GroundingMode = "optional"

# Whether the ask operates on a file already bound to this dialog thread
# (re-read from storage) instead of one fenced into the current turn.
# Intent owns the value (structural hint: has_thread_files); ExecutionPlanner maps
# ``thread_file`` to a direct ``platform.read_attachment`` call. Identity of the file
# is resolved deterministically in the application layer — never by the LLM (055).
FileReferenceKind = Literal["none", "thread_file"]
FILE_REFERENCE_DEFAULT: FileReferenceKind = "none"

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

# --- Response shape (intent → formatter) ---

# Form of the answer *body*, orthogonal to task_kind and routing. ``auto`` means "no
# explicit form requested: the Formatter chooses the block composition". The value set
# is closed (010): a new form is a contract change, not a prompt tweak.
#   comparison_table    — side-by-side comparison of 2+ objects along attributes.
#   document_analysis   — sections/risks/recommendations over one document.
#   plan                — ordered, actionable steps.
#   prose               — explanation without forced structure.
# ``choice_cards``/``greeting`` are deliberately absent: requires_user_choice and
# task_kind=social_conversation + style_hint already own those outcomes (050).
ResponseShape = Literal[
    "auto",
    "comparison_table",
    "document_analysis",
    "plan",
    "prose",
]
RESPONSE_SHAPE_DEFAULT: ResponseShape = "auto"

# --- Streaming (SSE) contract per turn ---

# How the user-facing answer is painted during one turn. Closed set (010): a new
# value is a contract change, not an env tweak.
#   structured_incremental — ContentDocument blocks are painted as they close; the
#                            final document is a superset of what was already shown
#                            (no replace, layout_shift_count == 0).
#   buffered               — one final frame, no preview (nothing to replace).
#   legacy_markdown         — GFM token stream + one handover from a worker draft
#                            (deprecated; keep while the Markdown parser is the fallback).
StreamingContract = Literal["structured_incremental", "buffered", "legacy_markdown"]
STREAMING_CONTRACT_DEFAULT: StreamingContract = "legacy_markdown"

# --- Answer writer (single-writer contract, P1a) ---

# Which component owns the user-visible deliverable for one turn. Exactly one writer:
#   worker    — Researcher/worker writes the final GFM; Formatter renders it
#               deterministically (no LLM rewrite, no replacement of the draft).
#   formatter — Formatter is the only writer (restructure, clarify/choice, verbatim,
#               locale mismatch, revision); the worker draft must not reach the client.
# Closed set (010): a new owner is a contract change, not an env tweak.
PresentationOwner = Literal["worker", "formatter"]
PRESENTATION_OWNER_DEFAULT: PresentationOwner = "formatter"

# --- Untrusted content (attachments, MCP/tool output) ---

# How a payload with detected injection signals may be used. ``allow`` keeps it
# verbatim, ``mask`` redacts the matched spans, ``quarantine``/``reject`` let
# nothing reach the prompt and require human review (020, OWASP LLM01).
UntrustedContentAction = Literal["allow", "mask", "quarantine", "reject"]

__all__ = [
    "CONTENT_GENERATION_CAPABILITY",
    "DOCUMENT_GENERATION_CAPABILITY",
    "FILE_REFERENCE_DEFAULT",
    "GROUNDING_DEFAULT",
    "LOW_RISK_ROUTE_STRATEGIES",
    "PRESENTATION_OWNER_DEFAULT",
    "RESPONSE_SHAPE_DEFAULT",
    "STREAMING_CONTRACT_DEFAULT",
    "SUBSTANTIVE_USER_PAYLOAD_CHARS",
    "TRANSFORMATION_DEFAULT",
    "VERBATIM_EXTRACTION_CAPABILITY",
    "AgentRole",
    "ContinuationKind",
    "ExecutionStrategy",
    "FileReferenceKind",
    "GroundingMode",
    "ModelTier",
    "PresentationOwner",
    "ResponseShape",
    "RouteStrategy",
    "StreamingContract",
    "TaskKind",
    "TransformationKind",
    "UnderspecificationKind",
    "UntrustedContentAction",
]
