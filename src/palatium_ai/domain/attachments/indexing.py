# src/palatium_ai/domain/attachments/indexing.py

"""Pending payload for HITL-gated attachment indexing (020, 070).

Indexing a file writes to the knowledge base, which is irreversible, so the
chunks are prepared first, parked under a task id, and only handed to
``platform.ingest_document`` after the matching HITL card is approved. The
payload carries no raw bytes — only the sanitized chunks the reviewer approves.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from palatium_ai.domain.agents.text_ingestor import TextChunk


class AttachmentIndexPayload(BaseModel):
    """Sanitized chunks awaiting HITL approval for ``platform.ingest_document``."""

    model_config = {"frozen": True}

    task_id: str = Field(min_length=1, max_length=128)
    attachment_id: UUID
    user_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    org_id: str = Field(default="", max_length=128)
    document_title: str = Field(default="", max_length=256)
    mime_type: str = Field(default="", max_length=128)
    chunks: tuple[TextChunk, ...] = ()


__all__ = ["AttachmentIndexPayload"]
