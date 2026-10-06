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
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.security.prompt_injection import (
    PromptInjectionReport,
    redact_findings,
    scan_prompt_injection,
)
from palatium_ai.core.security.secret_scanner import SecretScanError, scan_text
from palatium_ai.domain.attachments.active_content import ooxml_contains_active_content
from palatium_ai.domain.attachments.content import AttachmentContent, AttachmentScanSummary
from palatium_ai.domain.attachments.pii_policy import (
    AttachmentPiiPolicyMode,
    apply_attachment_pii_policy,
)
from palatium_ai.domain.attachments.policies import AttachmentIntakePolicy
from palatium_ai.domain.attachments.sniff import sniff_media_type
from palatium_ai.domain.attachments.types import AttachmentRejectionReason, AttachmentStatus
from palatium_ai.domain.memory.pii import mask_pii_in_text
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
_OOXML_MIME_TYPES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)


@dataclass(frozen=True, slots=True)
class AttachmentPipelineOutcome:
    """What the service should persist after one pipeline run."""

    status: AttachmentStatus
    stored_size_bytes: int
    rejection_reason: AttachmentRejectionReason | None = None
    error: str | None = None
    content: AttachmentContent | None = None
    #: Magic-byte MIME when sniff succeeded; may replace a lying client declaration.
    detected_mime_type: str | None = None

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
        pii_policy: AttachmentPiiPolicyMode = "tag",
    ) -> None:
        self._blob_store = blob_store
        self._scanner = malware_scanner
        self._parser = document_parser
        self._thresholds = thresholds
        self._pii_policy = pii_policy

    def supports_media_type(self, mime_type: str) -> bool:
        """Whether the deployment has a parser for this media type (020).

        Intake consults this so the domain registry and the wired parsers cannot
        drift: a media type that is "known" but unparsable is refused before any
        blob or row exists, instead of after a wasted upload + scan round-trip.
        """
        return self._parser.supports(mime_type)

    async def run(
        self,
        attachment: Attachment,
        *,
        limits: AttachmentLimits,
        force_mask_injection: bool = False,
    ) -> AttachmentPipelineOutcome:
        """Execute every gate for ``attachment`` and return the persistable outcome.

        ``force_mask_injection`` is reserved for manager-approved quarantine restore:
        injection signals that would quarantine/reject are downgraded to ``mask`` only.
        """
        stored = await self._read_stored(attachment, limits=limits)
        if isinstance(stored, AttachmentPipelineOutcome):
            return stored
        data, size_bytes = stored

        sniffed = sniff_media_type(data)
        mime_decision = AttachmentIntakePolicy.content_matches_declared(
            declared_mime=attachment.mime_type,
            detected_mime=sniffed,
            filename=attachment.filename,
        )
        if mime_decision.refused:
            logger.warning(
                "attachment refused by mime sniff",
                attachment_id=str(attachment.id),
                declared=attachment.mime_type,
                detected=sniffed or "",
                rejection_reason=mime_decision.reason,
            )
            return AttachmentPipelineOutcome(
                status="rejected",
                rejection_reason=mime_decision.reason or "mime_mismatch",
                stored_size_bytes=size_bytes,
                error="uploaded content does not match the declared media type",
                detected_mime_type=sniffed if sniffed and sniffed != "text/*" else None,
            )
        # Concrete binary sniff wins; text/* keeps the declared subtype (csv/md/plain).
        effective_mime = sniffed if sniffed and sniffed != "text/*" else attachment.mime_type

        verdict = await self._scanner.scan(data, filename=attachment.filename)
        if not verdict.admitted:
            return _scan_refusal(verdict, size_bytes=size_bytes)

        active = _active_content_refusal(
            attachment=attachment,
            data=data,
            effective_mime=effective_mime,
            size_bytes=size_bytes,
        )
        if active is not None:
            return active

        parsed = await self._parse(data, attachment, mime_type=effective_mime)
        if isinstance(parsed, AttachmentPipelineOutcome):
            return parsed

        return self._admit_extracted(
            attachment=attachment,
            parsed=parsed,
            effective_mime=effective_mime,
            size_bytes=size_bytes,
            force_mask_injection=force_mask_injection,
        )

    def _admit_extracted(
        self,
        *,
        attachment: Attachment,
        parsed: ParsedDocument,
        effective_mime: str,
        size_bytes: int,
        force_mask_injection: bool,
    ) -> AttachmentPipelineOutcome:
        """Run PII / secret / injection gates on already-parsed text."""
        pii = apply_attachment_pii_policy(parsed.flow_text, mode=self._pii_policy)
        if pii.refuse:
            logger.warning(
                "attachment refused: pii policy reject",
                attachment_id=str(attachment.id),
                rejection_reason="pii_detected",
            )
            return AttachmentPipelineOutcome(
                status="rejected",
                rejection_reason="pii_detected",
                stored_size_bytes=size_bytes,
                error="extracted content matched PII detectors under reject policy",
                detected_mime_type=effective_mime if effective_mime != attachment.mime_type else None,
            )

        try:
            scan_text(parsed.flow_text, field="attachment.extracted")
        except SecretScanError:
            logger.warning(
                "attachment refused: secret pattern in extracted text",
                attachment_id=str(attachment.id),
            )
            return AttachmentPipelineOutcome(
                status="rejected",
                rejection_reason="parse_failed",
                stored_size_bytes=size_bytes,
                error="extracted content contains a blocked credential pattern",
                detected_mime_type=effective_mime if effective_mime != attachment.mime_type else None,
            )

        report = scan_prompt_injection(parsed.flow_text)
        prepared = UntrustedContentPolicy.prepare(parsed.flow_text, report, thresholds=self._thresholds)
        if force_mask_injection and prepared.action in _REFUSING_ACTIONS:
            prepared = UntrustedContentResult(
                action="mask",
                text=redact_findings(parsed.flow_text, report.findings),
                worst_severity=prepared.worst_severity,
                matched_rules=prepared.matched_rules,
            )
        if prepared.action in _REFUSING_ACTIONS:
            return _injection_refusal(prepared, parsed=parsed, report=report, size_bytes=size_bytes)
        detected_for_row = effective_mime if effective_mime != attachment.mime_type else None
        safe_text = _prompt_body(prepared.action, parsed, prepared)
        if pii.mode == "mask":
            safe_text = mask_pii_in_text(safe_text)
        return _content_outcome(
            parsed=parsed,
            report=report,
            prepared=prepared,
            safe_text=safe_text,
            size_bytes=size_bytes,
            detected_mime_type=detected_for_row,
            contains_pii=pii.contains_pii,
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

    async def _parse(
        self,
        data: bytes,
        attachment: Attachment,
        *,
        mime_type: str,
    ) -> ParsedDocument | AttachmentPipelineOutcome:
        """Parse untrusted bytes; a parser refusal is a typed rejection, not a crash."""
        if not self._parser.supports(mime_type):
            return AttachmentPipelineOutcome(
                status="rejected",
                rejection_reason="mime_not_allowed",
                stored_size_bytes=len(data),
                error=f"no parser registered for {mime_type}",
                detected_mime_type=mime_type,
            )
        try:
            parsed = await self._parser.parse(data, mime_type=mime_type, filename=attachment.filename)
        except DocumentParseError as exc:
            logger.warning(
                "attachment parse refused",
                attachment_id=str(attachment.id),
                mime_type=mime_type,
                error=str(exc),
            )
            reason = exc.rejection_reason or "parse_failed"
            return AttachmentPipelineOutcome(
                status="rejected",
                rejection_reason=reason,
                stored_size_bytes=len(data),
                error="document could not be parsed",
                detected_mime_type=mime_type,
            )
        agent_metrics.record_attachment_parse(
            extraction_source=parsed.extraction_source,
            media_kind=_media_kind(mime_type),
        )
        return parsed


def _media_kind(mime_type: str) -> str:
    """Closed media_kind vocabulary for Prometheus cardinality (040)."""
    normalized = mime_type.strip().lower()
    if normalized.startswith("image/"):
        return "image"
    if normalized == "application/pdf":
        return "pdf"
    if normalized.startswith("text/"):
        return "text"
    if "wordprocessingml" in normalized or "spreadsheetml" in normalized or "presentationml" in normalized:
        return "office"
    return "other"


def _active_content_refusal(
    *,
    attachment: Attachment,
    data: bytes,
    effective_mime: str,
    size_bytes: int,
) -> AttachmentPipelineOutcome | None:
    """Refuse OOXML packages that carry macros or OLE embeddings (020)."""
    if effective_mime not in _OOXML_MIME_TYPES or not ooxml_contains_active_content(data):
        return None
    logger.warning(
        "attachment refused: ooxml active content",
        attachment_id=str(attachment.id),
        rejection_reason="active_content",
        mime_type=effective_mime,
    )
    return AttachmentPipelineOutcome(
        status="rejected",
        rejection_reason="active_content",
        stored_size_bytes=size_bytes,
        error="document package contains macros or embedded OLE objects",
        detected_mime_type=effective_mime if effective_mime != attachment.mime_type else None,
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
    detected_mime_type: str | None = None,
    contains_pii: bool = False,
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
        contains_pii=contains_pii,
    )
    return AttachmentPipelineOutcome(
        status="ready",
        stored_size_bytes=size_bytes,
        content=content,
        detected_mime_type=detected_mime_type,
    )


__all__ = ["AttachmentPipeline", "AttachmentPipelineOutcome"]
