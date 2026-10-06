# src/palatium_ai/core/types/retrieval.py

"""Shared hybrid-retrieval constants (knowledge + memory)."""

from typing import Literal

HybridFusion = Literal["weighted", "rrf"]

# Default RRF constant from Cormack/Clarke/Buettcher.
DEFAULT_RRF_K = 60

__all__ = ["DEFAULT_RRF_K", "HybridFusion"]
