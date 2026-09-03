# src/palatium_ai/application/agents/text_ingestor/chunking.py

"""Детерминированный чанкинг для TextIngestor (без LLM на scaffold-этапе)."""

from __future__ import annotations

from palatium_ai.application.agents.text_ingestor.config import CHUNK_OVERLAP_CHARS
from palatium_ai.domain.agents.text_ingestor import ChunkingStrategy, TextChunk


def normalize_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


def _effective_overlap(max_chars: int) -> int:
    if max_chars <= CHUNK_OVERLAP_CHARS:
        return max(0, max_chars // 4)
    return CHUNK_OVERLAP_CHARS


def _chunk_fixed_window(text: str, max_chars: int, *, overlap: int | None = None) -> list[TextChunk]:
    effective_overlap = overlap if overlap is not None else _effective_overlap(max_chars)
    if max_chars <= effective_overlap:
        effective_overlap = 0
    chunks: list[TextChunk] = []
    step = max(max_chars - effective_overlap, 1)
    start = 0
    index = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        piece = text[start:end].strip()
        if piece:
            chunks.append(
                TextChunk(
                    index=index,
                    text=piece,
                    char_start=start,
                    char_end=end,
                )
            )
            index += 1
        if end >= len(text):
            break
        start += step
    return chunks


def _chunk_paragraphs(text: str, max_chars: int) -> list[TextChunk]:
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    chunks: list[TextChunk] = []
    search_from = 0
    for index, paragraph in enumerate(paragraphs):
        start = text.find(paragraph, search_from)
        if start < 0:
            start = search_from
        end = start + len(paragraph)
        search_from = end
        if len(paragraph) <= max_chars:
            chunks.append(
                TextChunk(
                    index=index,
                    text=paragraph,
                    char_start=start,
                    char_end=end,
                )
            )
            continue
        nested = _chunk_fixed_window(paragraph, max_chars)
        for nested_chunk in nested:
            chunks.append(
                TextChunk(
                    index=len(chunks),
                    text=nested_chunk.text,
                    char_start=start + nested_chunk.char_start,
                    char_end=start + nested_chunk.char_end,
                )
            )
    return chunks


def chunk_text(text: str, *, max_chars: int) -> tuple[ChunkingStrategy, tuple[TextChunk, ...]]:
    """Выбирает стратегию и возвращает чанки."""
    normalized = normalize_text(text)
    if not normalized:
        return "paragraph", ()

    paragraphs = [part for part in normalized.split("\n\n") if part.strip()]
    if len(paragraphs) > 1 and all(len(part) <= max_chars for part in paragraphs):
        return "paragraph", tuple(_chunk_paragraphs(normalized, max_chars))

    window_chunks = _chunk_fixed_window(normalized, max_chars)
    if len(window_chunks) <= 1 and paragraphs:
        return "paragraph", tuple(_chunk_paragraphs(normalized, max_chars))
    return "fixed_window", tuple(window_chunks)


def compute_chunking_confidence(chunks: tuple[TextChunk, ...], *, max_chars: int) -> float:
    if not chunks:
        return 0.0
    if any(len(chunk.text) > max_chars for chunk in chunks):
        return 0.55
    return min(0.98, 0.75 + 0.05 * min(len(chunks), 4))
