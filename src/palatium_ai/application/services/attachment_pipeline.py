# src/palatium_ai/application/services/attachment_pipeline.py

"""Deterministic attachment pipeline: scan -> parse -> injection gate -> content (020).

Every stage runs before any model sees the file, and every stage fails closed:
an unreachable AV engine, an unparsable payload or a truncated injection scan
all end as a refusal, never as "proceed without the check". The pipeline itself
performs no persistence — it returns a typed outcome and the service decides
what to write, which keeps the security decision testable without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from palatium_ai.core.logging import logger
from palatium_ai.core.security.prompt_injection import PromptInjectionReport, scan_prompt_injection
from palatium_ai.domain.attachments.content import AttachmentContent, AttachmentScanSummary
from palatium_ai.domain.attachments.types import AttachmentRejectionReason, AttachmentStatus
from palatium_ai.domain.policies.types import UntrustedContentAction
from palatium_ai.domain.policies.untrusted_content import (
    DEFAULT_UNTRUSTED_CONTENT_THRESHOLDS,
    UntrustedContentPolicy,
    UntrustedContentResult,
    UntrustedContentThresholds,
)
from palatium_ai.domain.ports.document_parser import DocumentParseError

if TYPE_CHECKING:
    from palatium_ai.domain.attachments import Attachment, AttachmentLimits
    from palatium_ai.domain.ports.blob_store import BlobStorePort
    from palatium_ai.domain.ports.document_parser import DocumentParserPort, ParsedDocument
    from palatium_ai.domain.ports.scanner import MalwareScannerPort, ScanVerdict

_REFUSING_ACTIONS = frozenset({"quarantine", "reject"})


@dataclass(frozen=True, slots=True)
class AttachmentPipelineOutcome:
    """What the service should persist after one pipeline run."""

    status: AttachmentStatus
    stored_size_bytes: int
    rejection_reason: AttachmentRejectionReason | None = None
    error: str | None = None
    content: AttachmentContent | None = None

    @property
    def admitted(self) -> bool:
        """True when the attachment reached the usable state."""
        return self.status == "ready"


class AttachmentPipeline:
    """Runs the pre-model security pipeline for one attachment."""

    def __init__(
        self,
        *,
        blob_store: BlobStorePort,
        malware_scanner: MalwareScannerPort,
        document_parser: DocumentParserPort,
        thresholds: UntrustedContentThresholds = DEFAULT_UNTRUSTED_CONTENT_THRESHOLDS,
    ) -> None:
        self._blob_store = blob_store
        self._scanner = malware_scanner
        self._parser = document_parser
        self._thresholds = thresholds

    async def run(self, attachment: Attachment, *, limits: AttachmentLimits) -> AttachmentPipelineOutcome:
        """Execute every gate for ``attachment`` and return the persistable outcome."""
        stored = await self._read_stored(attachment, limits=limits)
        if isinstance(stored, AttachmentPipelineOutcome):
            return stored
        data, size_bytes = stored

        verdict = await self._scanner.scan(data, filename=attachment.filename)
        if not verdict.admitted:
            return _scan_refusal(verdict, size_bytes=size_bytes)

        parsed = await self._parse(data, attachment)
        if isinstance(parsed, AttachmentPipelineOutcome):
            return parsed

        report = scan_prompt_injection(parsed.flow_text)
        prepared = UntrustedContentPolicy.prepare(parsed.flow_text, report, thresholds=self._thresholds)
        if prepared.action in _REFUSING_ACTIONS:
            return _injection_refusal(prepared, parsed=parsed, report=report, size_bytes=size_bytes)
        return _content_outcome(
            parsed=parsed,
            report=report,
            prepared=prepared,
            safe_text=_prompt_body(prepared.action, parsed, prepared),
            size_bytes=size_bytes,
        )

    async def _read_stored(
        self,
        attachment: Attachment,
        *,
        limits: AttachmentLimits,
    ) -> tuple[bytes, int] | AttachmentPipelineOutcome:
        """Confirm the client's upload against storage before reading it (020).

        The declared size comes from the client and cannot be trusted; the object
        store is the authority for both the size cap and the existence check.
        """
        stat = await self._blob_store.stat(attachment.blob_key)
        if stat is None:
            return AttachmentPipelineOutcome(
                status="rejected",
                rejection_reason="not_uploaded",
                stored_size_bytes=0,
                error="uploaded object is missing",
            )
        if stat.size_bytes <= 0:
            return AttachmentPipelineOutcome(
                status="rejected",
                rejection_reason="size_invalid",
                stored_size_bytes=stat.size_bytes,
                error="uploaded object is empty",
            )
        if stat.size_bytes > limits.max_size_bytes:
            return AttachmentPipelineOutcome(
                status="rejected",
                rejection_reason="size_exceeded",
                stored_size_bytes=stat.size_bytes,
                error="uploaded object exceeds the configured size cap",
            )
        data = await self._blob_store.read_bytes(attachment.blob_key)
        return data, stat.size_bytes

    async def _parse(self, data: bytes, attachment: Attachment) -> ParsedDocument | AttachmentPipelineOutcome:
        """Parse untrusted bytes; a parser refusal is a typed rejection, not a crash."""
        if not self._parser.supports(attachment.mime_type):
            return AttachmentPipelineOutcome(
                status="rejected",
                rejection_reason="mime_not_allowed",
                stored_size_bytes=len(data),
                error=f"no parser registered for {attachment.mime_type}",
            )
        try:
            return await self._parser.parse(data, mime_type=attachment.mime_type, filename=attachment.filename)
        except DocumentParseError as exc:
            logger.warning(
                "attachment parse refused",
                attachment_id=str(attachment.id),
                mime_type=attachment.mime_type,
                error=str(exc),
            )
            return AttachmentPipelineOutcome(
                status="rejected",
                rejection_reason="parse_failed",
                stored_size_bytes=len(data),
                error="document could not be parsed",
            )


def _scan_refusal(verdict: ScanVerdict, *, size_bytes: int) -> AttachmentPipelineOutcome:
    """Map a non-admitting verdict to the right typed refusal (020).

    ``infected`` is evidence of malware; anything else means the engine could not
    answer. Both refuse, but conflating them would hide an outage as an attack.
    """
    if verdict.infected:
        reason: AttachmentRejectionReason = "malware_detected"
        error = "malware signature detected"
    else:
        reason = "scan_failed"
        error = "malware scanner could not produce a verdict"
    logger.warning(
        "attachment refused by scanner",
        engine=verdict.engine,
        rejection_reason=reason,
        signature=verdict.signature or "",
    )
    return AttachmentPipelineOutcome(
        status="quarantined",
        rejection_reason=reason,
        stored_size_bytes=size_bytes,
        error=error,
    )


def _injection_refusal(
    prepared: UntrustedContentResult,
    *,
    parsed: ParsedDocument,
    report: PromptInjectionReport,
    size_bytes: int,
) -> AttachmentPipelineOutcome:
    """Quarantine/reject outcome; no derived content is stored (fail closed)."""
    logger.warning(
        "attachment refused by injection gate",
        action=prepared.action,
        worst_severity=prepared.worst_severity,
        matched_rules=",".join(prepared.matched_rules[:8]),
        parse_truncated=parsed.truncated,
        scan_truncated=report.truncated,
    )
    return AttachmentPipelineOutcome(
        status="quarantined" if prepared.action == "quarantine" else "rejected",
        rejection_reason="injection_detected",
        stored_size_bytes=size_bytes,
        error=f"prompt injection signal ({prepared.worst_severity})",
    )


def _prompt_body(action: UntrustedContentAction, parsed: ParsedDocument, prepared: UntrustedContentResult) -> str:
    """Pick the stored prompt body.

    ``mask`` must use the redacted flow text, because redaction spans are computed
    on the marker-free view. ``allow`` keeps the page-addressed extraction so page
    citations survive into the turn.
    """
    if action == "mask":
        return prepared.text
    return parsed.text


def _content_outcome(
    *,
    parsed: ParsedDocument,
    report: PromptInjectionReport,
    prepared: UntrustedContentResult,
    safe_text: str,
    size_bytes: int,
) -> AttachmentPipelineOutcome:
    """Build the usable outcome with the scan summary attached for audit."""
    summary = AttachmentScanSummary(
        action=prepared.action,
        worst_severity=report.worst_severity,
        matched_rules=prepared.matched_rules,
        truncated=report.truncated,
    )
    content = AttachmentContent(
        pages=parsed.pages,
        scan=summary,
        safe_text=safe_text,
        page_count=parsed.page_count,
        truncated=parsed.truncated,
    )
    return AttachmentPipelineOutcome(status="ready", stored_size_bytes=size_bytes, content=content)


__all__ = ["AttachmentPipeline", "AttachmentPipelineOutcome"]
