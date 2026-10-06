# src/palatium_ai/core/types/knowledge.py

"""Closed vocabularies for knowledge retrieval (config + domain scoring)."""

from __future__ import annotations

from palatium_ai.core.types.retrieval import DEFAULT_RRF_K, HybridFusion

# Alias kept for existing KnowledgeConfig / domain imports (010: one constant).
KnowledgeHybridFusion = HybridFusion

__all__ = ["DEFAULT_RRF_K", "KnowledgeHybridFusion"]
