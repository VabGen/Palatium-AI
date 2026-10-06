# src/palatium_ai/domain/policies/untrusted_content.py

"""How untrusted content (attachments, MCP/tool output) may enter a prompt (020).

Pure, deterministic gate: a scan report plus thresholds decide one action. The
policy never calls an LLM and never touches I/O, so it is unit-testable without
network or model fakes (055). Fencing stays mandatory on top of this decision —
the scanner is a signal, not the only defence (020, OWASP LLM01).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from palatium_ai.core.security.prompt_injection import (
    PromptInjectionReport,
    redact_findings,
    severity_rank,
)

from .types import UntrustedContentAction

# Rank cut-offs mirror the ADR mapping (none/low → allow, medium → mask,
# high → quarantine, critical → reject). Values are overridable from config.
_DEFAULT_MASK_RANK = 2
_DEFAULT_QUARANTINE_RANK = 3
_DEFAULT_REJECT_RANK = 4


class UntrustedContentThresholds(BaseModel):
    """Severity cut-offs for the allow/mask/quarantine/reject ladder."""

    model_config = {"frozen": True}

    mask_at_rank: int = Field(default=_DEFAULT_MASK_RANK, ge=1, le=4)
    quarantine_at_rank: int = Field(default=_DEFAULT_QUARANTINE_RANK, ge=1, le=4)
    reject_at_rank: int = Field(default=_DEFAULT_REJECT_RANK, ge=1, le=4)

    @model_validator(mode="after")
    def _ladder_is_monotonic(self) -> UntrustedContentThresholds:
        """Fail closed on misconfiguration instead of silently loosening the gate."""
        if not self.mask_at_rank <= self.quarantine_at_rank <= self.reject_at_rank:
            msg = "untrusted-content thresholds must satisfy mask_at_rank <= quarantine_at_rank <= reject_at_rank"
            raise ValueError(msg)
        return self


DEFAULT_UNTRUSTED_CONTENT_THRESHOLDS = UntrustedContentThresholds()


class UntrustedContentResult(BaseModel):
    """Decision plus the only text that may be handed to an LLM prompt."""

    model_config = {"frozen": True}

    action: UntrustedContentAction
    text: str
    worst_severity: str = Field(default="none", max_length=16)
    matched_rules: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        """True when the payload may reach a prompt (verbatim or redacted)."""
        return self.action in ("allow", "mask")


class UntrustedContentPolicy:
    """Pure gate turning a scan report into one action and the safe text."""

    @staticmethod
    def decide(
        report: PromptInjectionReport,
        *,
        thresholds: UntrustedContentThresholds = DEFAULT_UNTRUSTED_CONTENT_THRESHOLDS,
    ) -> UntrustedContentAction:
        """Rank the worst finding, but never trust an incomplete scan.

        A truncated report proves the scan stopped early, so spans beyond the cap
        were never redacted. Treating that as ``allow``/``mask`` would let an
        attacker pad a payload with benign matches to push a real directive past
        the cap, so an incomplete scan quarantines (020: fail closed).
        """
        rank = severity_rank(report.worst_severity)
        if rank >= thresholds.reject_at_rank:
            return "reject"
        if rank >= thresholds.quarantine_at_rank:
            return "quarantine"
        if report.truncated:
            return "quarantine"
        if rank >= thresholds.mask_at_rank:
            return "mask"
        return "allow"

    @staticmethod
    def requires_human_review(
        report: PromptInjectionReport,
        *,
        thresholds: UntrustedContentThresholds = DEFAULT_UNTRUSTED_CONTENT_THRESHOLDS,
    ) -> bool:
        """Quarantine and reject are reviewed by a human, never dropped silently (020)."""
        return UntrustedContentPolicy.decide(report, thresholds=thresholds) in ("quarantine", "reject")

    @staticmethod
    def prepare(
        text: str,
        report: PromptInjectionReport,
        *,
        thresholds: UntrustedContentThresholds = DEFAULT_UNTRUSTED_CONTENT_THRESHOLDS,
    ) -> UntrustedContentResult:
        """Return the action and the prompt-safe text (empty for quarantine/reject)."""
        action = UntrustedContentPolicy.decide(report, thresholds=thresholds)
        if action == "reject" or action == "quarantine":
            safe_text = ""
        elif action == "mask":
            safe_text = redact_findings(text, report.findings)
        else:
            safe_text = text
        return UntrustedContentResult(
            action=action,
            text=safe_text,
            worst_severity=report.worst_severity,
            matched_rules=_distinct_rules(report),
        )


def _distinct_rules(report: PromptInjectionReport) -> tuple[str, ...]:
    """Unique matched rule ids in first-match order (bounded audit metadata)."""
    seen: list[str] = []
    for finding in report.findings:
        if finding.rule not in seen:
            seen.append(finding.rule)
    return tuple(seen)


def budget_untrusted_text(text: str, *, max_chars: int) -> str:
    """Fit already-fenced untrusted text into a turn budget.

    Truncation keeps both ends and states the cut explicitly. Silently cutting
    the tail is unsafe here: an attacker could pad a payload so the real
    directive lands past the cut, and a reader would never know text was lost.
    """
    if max_chars < 64:
        raise ValueError("max_chars must be >= 64")
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    marker = f"\n… [attachment context truncated {omitted} chars] …\n"
    if max_chars <= len(marker) + 24:
        return text[:max_chars]
    keep = (max_chars - len(marker)) // 2
    return f"{text[:keep]}{marker}{text[-keep:]}"
