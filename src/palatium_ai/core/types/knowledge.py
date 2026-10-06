# src/palatium_ai/core/types/knowledge.py

"""Closed vocabularies for knowledge retrieval (config + domain scoring)."""

from __future__ import annotations

from typing import Literal

KnowledgeHybridFusion = Literal["weighted", "rrf"]

# Default RRF constant from Cormack/Clarke/Buettcher; KnowledgeConfig.rrf_k default.
DEFAULT_RRF_K = 60

__all__ = ["DEFAULT_RRF_K", "KnowledgeHybridFusion"]
