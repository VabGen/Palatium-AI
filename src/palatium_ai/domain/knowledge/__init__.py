# src/palatium_ai/domain/knowledge/__init__.py

"""Knowledge domain contracts."""

from palatium_ai.domain.knowledge.port import KnowledgePort
from palatium_ai.domain.knowledge.types import (
    IngestDocumentCommand,
    IngestDocumentResult,
    KnowledgeSearchHit,
    KnowledgeSearchResult,
    SearchKnowledgeQuery,
)

__all__ = [
    "IngestDocumentCommand",
    "IngestDocumentResult",
    "KnowledgePort",
    "KnowledgeSearchHit",
    "KnowledgeSearchResult",
    "SearchKnowledgeQuery",
]
