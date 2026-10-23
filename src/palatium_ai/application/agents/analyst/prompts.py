# src/palatium_ai/application/agents/analyst/prompts.py

"""Analyst prompts (030)."""

from palatium_ai.domain.policies.assistant_identity import IDENTITY_CAPABILITIES, IDENTITY_CORE

ANALYST_SYSTEM_PROMPT = (
    IDENTITY_CORE
    + IDENTITY_CAPABILITIES
    + """## YOUR JOB IN THIS TURN
Produce a structured analysis of the user request using only provided context.
Do NOT invent MCP/tool results or external metrics.
Respond as JSON: {"summary": str, "confidence": float 0..1, "findings": [str, ...]}.
"""
)
