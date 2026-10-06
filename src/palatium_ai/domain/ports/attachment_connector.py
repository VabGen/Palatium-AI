# src/palatium_ai/domain/ports/attachment_connector.py

"""External file sources for attachments (G10) — EDMS-first, no Drive invent.

Cloud connectors (Drive/SharePoint) stay deferred until tenant ACL + EDMS MCP
(092) land. This port is the seam so product UI can discover connectors without
hard-coding vendor OAuth flows (055, 070).
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

ConnectorKind = Literal["edms", "drive", "sharepoint", "other"]


class AttachmentConnectorSource(BaseModel):
    """One discoverable external library a user may import from."""

    model_config = {"frozen": True}

    id: str = Field(min_length=1, max_length=128)
    kind: ConnectorKind
    label: str = Field(min_length=1, max_length=256)
    available: bool = False
    reason: str = Field(default="", max_length=512)


class AttachmentConnectorImportRequest(BaseModel):
    """Intent to pull a remote document into the attachment pipeline (HITL later)."""

    model_config = {"frozen": True}

    connector_id: str = Field(min_length=1, max_length=128)
    remote_ref: str = Field(min_length=1, max_length=512)
    user_id: str = Field(min_length=1, max_length=128)
    org_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    project_id: str | None = Field(default=None, max_length=128)


class AttachmentConnectorPort(Protocol):
    """List connector sources; import remains fail-closed until EDMS MCP lands."""

    async def list_sources(self, *, user_id: str, org_id: str) -> tuple[AttachmentConnectorSource, ...]:
        """Return connectors visible to the principal (may be empty)."""
        ...

    async def request_import(self, request: AttachmentConnectorImportRequest) -> None:
        """Start an import. Implementations must fail closed when not wired (020)."""
        ...


__all__ = [
    "AttachmentConnectorImportRequest",
    "AttachmentConnectorPort",
    "AttachmentConnectorSource",
    "ConnectorKind",
]
