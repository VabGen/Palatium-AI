# src/palatium_ai/infrastructure/connectors/disabled_attachment_connector.py

"""Fail-closed connector catalog until EDMS import is wired (G10)."""

from __future__ import annotations

from palatium_ai.domain.attachments.errors import AttachmentConnectorUnavailableError
from palatium_ai.domain.ports.attachment_connector import (
    AttachmentConnectorImportRequest,
    AttachmentConnectorSource,
)

_EDMS_REASON = "capability=unavailable; EDMS MCP import not wired yet (092); Drive/SharePoint deferred after EDMS."


class DisabledAttachmentConnector:
    """Advertises EDMS as the planned first connector; never invents Drive OAuth."""

    async def list_sources(self, *, user_id: str, org_id: str) -> tuple[AttachmentConnectorSource, ...]:
        _ = user_id, org_id
        return (
            AttachmentConnectorSource(
                id="edms",
                kind="edms",
                label="EDMS (Канцлер NEXT)",
                available=False,
                reason=_EDMS_REASON,
            ),
        )

    async def request_import(self, request: AttachmentConnectorImportRequest) -> None:
        """Refuse every import until the EDMS MCP write path exists (020, 092)."""
        sources = await self.list_sources(user_id=request.user_id, org_id=request.org_id)
        matched = next((item for item in sources if item.id == request.connector_id), None)
        reason = matched.reason if matched is not None else f"unknown connector {request.connector_id!r}"
        raise AttachmentConnectorUnavailableError(connector_id=request.connector_id, reason=reason)


__all__ = ["DisabledAttachmentConnector"]
