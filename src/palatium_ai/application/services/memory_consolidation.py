# src/palatium_ai/application/services/memory_consolidation.py

"""Deprecated import path — use ``memory_extract`` (extract axis, 060).

Kept as a thin re-export so older imports keep resolving during the rename.
"""

from __future__ import annotations

from palatium_ai.application.services.memory_extract import MemoryExtractJob, MemoryExtractService

# Legacy aliases (prefer MemoryExtract*).
ConsolidationJob = MemoryExtractJob
MemoryConsolidationService = MemoryExtractService

__all__ = [
    "ConsolidationJob",
    "MemoryConsolidationService",
    "MemoryExtractJob",
    "MemoryExtractService",
]
