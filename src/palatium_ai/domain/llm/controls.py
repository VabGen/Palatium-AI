# src/palatium_ai/domain/llm/controls.py

"""Vendor LLM control dials (2026) — independent of prompt prose (055).

``reasoning_effort`` steers depth/cost (OpenAI reasoning + Anthropic effort via LiteLLM).
``verbosity`` steers answer length (OpenAI ``text.verbosity`` via LiteLLM ``verbosity``).
They must stay separate axes: length ≠ thinking depth.
"""

from __future__ import annotations

from typing import Literal

#: LiteLLM / OpenAI reasoning_effort values (Anthropic maps via LiteLLM).
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]

#: OpenAI text.verbosity values forwarded as LiteLLM ``verbosity``.
TextVerbosity = Literal["low", "medium", "high"]

__all__ = ["ReasoningEffort", "TextVerbosity"]
