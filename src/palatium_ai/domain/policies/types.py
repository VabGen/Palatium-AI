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

LOW_RISK_ROUTE_STRATEGIES: frozenset[RouteStrategy] = frozenset(
    {"ack_only", "format_only"},
)

__all__ = [
    "AgentRole",
    "ContinuationKind",
    "ExecutionStrategy",
    "LOW_RISK_ROUTE_STRATEGIES",
    "ModelTier",
    "RouteStrategy",
    "TaskKind",
    "UnderspecificationKind",
]
