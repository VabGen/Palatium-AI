# src/palatium_ai/domain/ingest/commit.py

"""Pending document ingest payloads (off-graph HITL commit path)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.agents.text_ingestor import TextChunk


class IngestCommitPayload(BaseModel):
    """Serialized prepared chunks awaiting HITL-approved MCP ingest."""

    model_config = {"frozen": True}

    thread_id: str = Field(min_length=1, max_length=128)
    prepare_task_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(default="", max_length=128)
    document_id: str | None = Field(default=None, max_length=128)
    document_title: str | None = Field(default=None, max_length=256)
    mime_type: str | None = Field(default=None, max_length=128)
    chunks: tuple[TextChunk, ...] = ()
