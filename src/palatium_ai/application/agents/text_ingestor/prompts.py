# src/palatium_ai/application/agents/text_ingestor/prompts.py

"""Промпты TextIngestor — contextual prefix (Anthropic Contextual Retrieval)."""

from __future__ import annotations

from palatium_ai.domain.agents.text_ingestor import TextChunk

TEXT_INGESTOR_CONTEXT_PREFIX_SYSTEM_PROMPT = (
    "You generate short contextual prefixes for document chunks before embedding. "
    'Return JSON: {"prefixes": ["...", ...]} with one prefix per chunk, '
    "describing where the chunk sits in the document. No PII beyond the chunk."
)


def build_context_prefix_user_prompt(
    *,
    document_title: str | None,
    chunks: tuple[TextChunk, ...],
) -> str:
    lines: list[str] = []
    if document_title:
        lines.append(f"document_title: {document_title}")
    lines.append("chunks:")
    for chunk in chunks:
        lines.append(f"[{chunk.index}] {chunk.text[:800]}")
    return "\n".join(lines)
