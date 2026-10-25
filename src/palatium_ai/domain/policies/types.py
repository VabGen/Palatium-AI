# src/palatium_ai/domain/policies/types.py

"""Единый реестр осей и Literal-типов политик (055, 000)."""

from __future__ import annotations

from typing import Literal, cast, get_args

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

# Which attachments of the current turn the ask targets (Level 1 priority hierarchy).
#   auto   — no explicit plurality; a general ask covers every eligible file;
#   all    — the ask explicitly covers the whole set ("по всем документам");
#   single — the ask is about one file in the singular; several eligible files
#            then require the file-choice card before any worker runs (020, 055).
# Closed set (010): a new value is a contract change, not a prompt tweak.
AttachmentScope = Literal["auto", "all", "single"]
ATTACHMENT_SCOPE_DEFAULT: AttachmentScope = "auto"

# Modality filter for the ask ("что на картинке" vs "проанализируй договор").
#   any      — no modality named; every selected scope is eligible;
#   image    — image/* uploads only (WebP/PNG/JPEG scans, OCR path);
#   document — PDF/DOCX/XLSX/text uploads only.
# Closed set (010); the mime → kind mapping lives in ``domain.attachments.context``.
AttachmentModality = Literal["image", "document"]
AttachmentKind = Literal["any", "image", "document"]
ATTACHMENT_KIND_DEFAULT: AttachmentKind = "any"

# Whether the ask targets the files uploaded in *this* turn (the Intent Guard).
#   current_uploads — the uploads are the subject of the ask (default; fail-safe);
#   none            — the ask is explicitly not about them ("вопрос не про файлы"):
#                     the fenced text is withheld from every prompt, so a chitchat
#                     or memory turn cannot quote a document the user asked to ignore.
# Default keeps the evidence: dropping a fence the model needed causes invention,
# which is the more dangerous error (055). Only an explicit intent label detaches it.
AttachmentFocus = Literal["current_uploads", "none"]
ATTACHMENT_FOCUS_DEFAULT: AttachmentFocus = "current_uploads"

# Interactive memory mutation (E2E-01/03). Orthogonal to task_kind: the ask is an
# execution against the memory gate, so a worker must never answer it from prose.
#   save   — «запомни …»: stage platform.save_memory behind a HITL card;
#   forget — «забудь …»: resolve the stored entry, then stage platform.forget_memory.
# Closed set (010): a new mutation is a contract change, not a prompt tweak.
MemoryMutationKind = Literal["none", "save", "forget"]
MEMORY_MUTATION_DEFAULT: MemoryMutationKind = "none"

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

# --- Per-block display strategy while the document streams (W1) ---

# Which block types may show partial content while their JSON element is still open.
# Closed set (010); owned by ``domain/policies/stream_display.py``.
#   text_delta — the element's prose may be painted as it arrives. Safe only where a
#                prefix is a readable answer in progress (a paragraph).
#   skeleton   — reserved space, no partial content: a half-list or half-table makes
#                the user start reading wrong data.
#   on_close   — nothing at all until the element is complete: partial code or math is
#                misinformation, and a heading is too short to stream usefully.
StreamDisplay = Literal["text_delta", "skeleton", "on_close"]

# --- Generation contract and schema verdict (W0b) ---

# Which contract actually produced the document, after the rollout decision — so a
# metric can compare cohorts without reading agent internals (040).
FormatterGenerationPath = Literal["schema_first", "legacy_markdown"]

# Verdict of the generation attempt. Closed set (010). Which path emits which value:
#   valid        — the model output validated against ``ContentDocument`` (both paths).
#   invalid      — provider JSON failed the schema (``schema_first``: no repair loop).
#   empty_blocks — schema-valid document without blocks for a non-empty answer: the
#                  model dropped content the provider does not mark as required.
#   unsupported  — the provider refused ``stream`` + ``json_schema``, so no verdict
#                  exists and this attempt must not enter the validity ratio.
#   fallback     — ``legacy_markdown`` could not parse the Markdown after repairs and
#                  the turn is rendered deterministically instead.
# Provider/timeout failures are deliberately absent: ``palatium_agent_errors_total``
# already owns them, and counting a transport failure as a schema failure would put
# a non-schema event in the denominator (050).
FormatterSchemaOutcome = Literal["valid", "invalid", "empty_blocks", "unsupported", "fallback"]

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

# --- Formatter composition style (presentation axis) ---

# Soft composition bias handed to the Formatter as ``style_hint``. Closed set (010):
# a new style is a prompt/contract change. Defined here (not in the agent package) so
# the outbound sanitiser can strip these identifiers without a domain→application
# import; ``application/agents/formatter/config.py`` re-exports them (010).
FormatterStyleHint = Literal[
    "brand_sections_icons",
    "restructure_sections_icons",
    "choice_cards",
    "clarify_open",
    "revise_keep_structure",
    "plain_text",
    "content_generation",
    "document_generation",
    "social_reply",
]
#: Runtime view of the Literal — one source, no hand-maintained copy (010).
FORMATTER_STYLE_HINTS: tuple[FormatterStyleHint, ...] = cast(
    "tuple[FormatterStyleHint, ...]",
    get_args(FormatterStyleHint),
)

__all__ = [
    "ATTACHMENT_FOCUS_DEFAULT",
    "ATTACHMENT_KIND_DEFAULT",
    "ATTACHMENT_SCOPE_DEFAULT",
    "CONTENT_GENERATION_CAPABILITY",
    "DOCUMENT_GENERATION_CAPABILITY",
    "FILE_REFERENCE_DEFAULT",
    "FORMATTER_STYLE_HINTS",
    "GROUNDING_DEFAULT",
    "LOW_RISK_ROUTE_STRATEGIES",
    "MEMORY_MUTATION_DEFAULT",
    "PRESENTATION_OWNER_DEFAULT",
    "RESPONSE_SHAPE_DEFAULT",
    "STREAMING_CONTRACT_DEFAULT",
    "SUBSTANTIVE_USER_PAYLOAD_CHARS",
    "TRANSFORMATION_DEFAULT",
    "VERBATIM_EXTRACTION_CAPABILITY",
    "AgentRole",
    "AttachmentFocus",
    "AttachmentKind",
    "AttachmentModality",
    "AttachmentScope",
    "ContinuationKind",
    "ExecutionStrategy",
    "FileReferenceKind",
    "FormatterGenerationPath",
    "FormatterSchemaOutcome",
    "FormatterStyleHint",
    "GroundingMode",
    "MemoryMutationKind",
    "ModelTier",
    "PresentationOwner",
    "ResponseShape",
    "RouteStrategy",
    "StreamDisplay",
    "StreamingContract",
    "TaskKind",
    "TransformationKind",
    "UnderspecificationKind",
    "UntrustedContentAction",
]
