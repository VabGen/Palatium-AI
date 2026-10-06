# src/palatium_ai/domain/attachments/indexing.py

"""Pending payloads for HITL-gated attachment flows (020, 070).

Indexing a file writes to the knowledge base, which is irreversible, so the
chunks are prepared first, parked under a task id, and only handed to
``platform.ingest_document`` after the matching HITL card is approved. The
payload carries no raw bytes — only the sanitized chunks the reviewer approves.

**Project KB (G09):** durable ``mode=index`` ingest carries optional ``project_id``
on the attachment aggregate and index payload so RAG chunks can be scoped per
project via ``document_id`` prefix ``project:<id>:<attachment_id>`` without
widening the ``ingest_document`` MCP pin. Connectors (G10) are EDMS-first and
remain a discoverable disabled catalog until 092 import lands.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from palatium_ai.domain.agents.text_ingestor import TextChunk


class AttachmentProjectRef(BaseModel):
    """Scope key for project-scoped knowledge indexing (G09)."""

    model_config = {"frozen": True}

    project_id: str | None = Field(
        default=None,
        max_length=64,
        description="When set, index-mode ingest targets project KB instead of global knowledge.",
    )


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
    project_id: str | None = Field(default=None, max_length=64)
    chunks: tuple[TextChunk, ...] = ()

    def knowledge_document_id(self) -> str:
        """Stable ingest document id; stays within ``source_document_id`` varchar(128).

        Format ``project:<id>:<attachment_hex>`` — UUID without dashes keeps headroom
        under the 128-char column while remaining unique per attachment.
        """
        if self.project_id:
            return f"project:{self.project_id}:{self.attachment_id.hex}"
        return str(self.attachment_id)


class AttachmentRestorePayload(BaseModel):
    """Manager-approved quarantine restore for injection-only quarantine (020)."""

    model_config = {"frozen": True}

    task_id: str = Field(min_length=1, max_length=128)
    attachment_id: UUID
    user_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    org_id: str = Field(default="", max_length=128)


class AttachmentAnalyzePayload(BaseModel):
    """HITL-gated tabular analysis job (G15 ADA local path)."""

    model_config = {"frozen": True}

    task_id: str = Field(min_length=1, max_length=128)
    attachment_id: UUID
    user_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    org_id: str = Field(default="", max_length=128)
    instruction: str = Field(min_length=1, max_length=4_000)


__all__ = [
    "AttachmentAnalyzePayload",
    "AttachmentIndexPayload",
    "AttachmentProjectRef",
    "AttachmentRestorePayload",
]
