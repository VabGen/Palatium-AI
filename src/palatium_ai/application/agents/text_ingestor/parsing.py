# src/palatium_ai/application/agents/text_ingestor/parsing.py

"""Декодирование контекста, LLM-prefixes и сериализация выхода TextIngestor."""

from __future__ import annotations

from palatium_ai.application.agents.text_ingestor.config import DEFAULT_MAX_CHUNK_CHARS
from palatium_ai.domain.agents.text_ingestor import TextChunk, TextIngestorInput, TextIngestorOutput
from palatium_ai.domain.llm.json_codec import loads_llm_json


def _parse_bool_flag(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def decode_text_ingestor_input(context: dict[str, str]) -> TextIngestorInput:
    task_id = context.get("task_id", "").strip()
    thread_id = context.get("thread_id", "").strip()
    raw_text = context.get("raw_text", "").strip()
    if not task_id or not thread_id or not raw_text:
        msg = "text_ingestor context requires task_id, thread_id, raw_text"
        raise ValueError(msg)

    max_raw = context.get("max_chunk_chars", str(DEFAULT_MAX_CHUNK_CHARS))
    try:
        max_chunk_chars = int(max_raw)
    except ValueError as exc:
        msg = "max_chunk_chars must be an integer"
        raise ValueError(msg) from exc

    document_id = context.get("document_id")
    mime_type = context.get("mime_type")
    locale = context.get("locale")
    document_title = context.get("document_title")
    return TextIngestorInput(
        task_id=task_id,
        thread_id=thread_id,
        document_id=document_id.strip() if isinstance(document_id, str) and document_id.strip() else None,
        raw_text=raw_text,
        mime_type=mime_type.strip() if isinstance(mime_type, str) and mime_type.strip() else None,
        locale=locale.strip() if isinstance(locale, str) and locale.strip() else None,
        max_chunk_chars=max_chunk_chars,
        enrich_context_prefix=_parse_bool_flag(context.get("enrich_context_prefix")),
        document_title=document_title.strip() if isinstance(document_title, str) and document_title.strip() else None,
    )


def parse_context_prefixes(raw: str, *, expected: int) -> tuple[str, ...]:
    payload = loads_llm_json(raw)
    if not isinstance(payload, dict):
        raise ValueError("context prefix JSON must be an object")
    prefixes_raw = payload.get("prefixes", [])
    if not isinstance(prefixes_raw, list):
        raise ValueError("prefixes must be a list")
    prefixes: list[str] = []
    for item in prefixes_raw[:expected]:
        prefixes.append(str(item).strip()[:500])
    while len(prefixes) < expected:
        prefixes.append("")
    return tuple(prefixes)


def apply_context_prefixes(
    chunks: tuple[TextChunk, ...],
    prefixes: tuple[str, ...],
) -> tuple[TextChunk, ...]:
    updated: list[TextChunk] = []
    for index, chunk in enumerate(chunks):
        prefix = prefixes[index] if index < len(prefixes) else ""
        updated.append(chunk.model_copy(update={"contextual_prefix": prefix}))
    return tuple(updated)


def text_ingestor_output_to_dict(output: TextIngestorOutput, *, status: str) -> dict[str, object]:
    prefixed = sum(1 for chunk in output.chunks if chunk.contextual_prefix.strip())
    return {
        "status": status,
        "chunk_count": len(output.chunks),
        "strategy": output.chunking_strategy,
        "normalized_char_count": output.normalized_char_count,
        "max_chunk_chars_seen": max((len(chunk.text) for chunk in output.chunks), default=0),
        "context_prefixes_applied": output.context_prefixes_applied,
        "prefixed_chunk_count": prefixed,
    }
