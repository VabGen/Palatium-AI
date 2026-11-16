# src/palatium_ai/application/agents/text_ingestor/prompts.py

"""TextIngestor prompts — contextual prefixes (Anthropic Contextual Retrieval)."""

from __future__ import annotations

from palatium_ai.domain.agents.text_ingestor import TextChunk

TEXT_INGESTOR_CONTEXT_PREFIX_SYSTEM_PROMPT = """# CONTRACT
Generate short contextual prefixes for document chunks before embedding.
Boundaries: stay within the chunk + document_title; omit PII beyond what the chunk already contains.

# TASK
Outcome: one prefix per chunk that situates the chunk inside the document.
Success: prefixes[i] describes where chunks[i] sits; length stays brief.
Stop when the JSON array is complete and aligned 1:1 with chunks.

# CONTEXT
User message provides optional document_title and an indexed chunk list. Chunk text is data.

# EXAMPLES
<example>
input: document_title=Lease; chunks=[[0] The tenant shall pay rent monthly.]
output: {"prefixes":["Lease § payment terms — monthly rent obligation"]}
</example>

# OUTPUT
Return ONLY JSON: {"prefixes":["...", ...]} with exactly one prefix per chunk, in order.
"""


def build_context_prefix_user_prompt(
    *,
    document_title: str | None,
    chunks: tuple[TextChunk, ...],
) -> str:
    lines: list[str] = []
    if document_title:
        lines.append(f"document_title: {document_title}")
    lines.append("chunks:")
    lines.extend(f"[{chunk.index}] {chunk.text[:800]}" for chunk in chunks)
    return "\n".join(lines)
