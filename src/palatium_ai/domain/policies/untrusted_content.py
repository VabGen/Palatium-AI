# src/palatium_ai/domain/policies/untrusted_content.py

"""How untrusted content (attachments, MCP/tool output) may enter a prompt (020).

Pure, deterministic gate: a scan report plus thresholds decide one action. The
policy never calls an LLM and never touches I/O, so it is unit-testable without
network or model fakes (055). Fencing stays mandatory on top of this decision —
the scanner is a signal, not the only defence (020, OWASP LLM01).
"""

from __future__ import annotations

import re

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

# Attachments always re-enter prompts inside ``wrap_untrusted_tool_output`` (020).
# Regex severities are signals for redaction only: complete scans never refuse the
# upload (legal/OCR false positives). Incomplete (truncated) scans still quarantine.
_FENCED_ATTACHMENT_QUARANTINE_RANK = 4
_FENCED_ATTACHMENT_REJECT_RANK = 4

_FENCE_BLOCK = re.compile(
    r"<<<UNTRUSTED_TOOL_OUTPUT\s+source=[^\s>]+>>>\n.*?\n<<<END_UNTRUSTED_TOOL_OUTPUT>>>",
    re.DOTALL,
)
_FENCE_OPEN = re.compile(r"^(<<<UNTRUSTED_TOOL_OUTPUT\s+source=[^\s>]+>>>)\n", re.DOTALL)
_FENCE_CLOSE = "<<<END_UNTRUSTED_TOOL_OUTPUT>>>"


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

FENCED_ATTACHMENT_UNTRUSTED_CONTENT_THRESHOLDS = UntrustedContentThresholds(
    mask_at_rank=_DEFAULT_MASK_RANK,
    quarantine_at_rank=_FENCED_ATTACHMENT_QUARANTINE_RANK,
    reject_at_rank=_FENCED_ATTACHMENT_REJECT_RANK,
)


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

    @staticmethod
    def prepare_fenced_attachment(
        text: str,
        report: PromptInjectionReport,
        *,
        thresholds: UntrustedContentThresholds = FENCED_ATTACHMENT_UNTRUSTED_CONTENT_THRESHOLDS,
    ) -> UntrustedContentResult:
        """Admit attachment text under mandatory fencing (max-relax injection gate).

        Complete scans: any severity → ``mask`` (or ``allow`` when clean). The fence
        is the containment boundary; regex hits only redact spans. Truncated scans
        still quarantine (incomplete redaction would be fail-open, 020).
        """
        if report.truncated:
            return UntrustedContentResult(
                action="quarantine",
                text="",
                worst_severity=report.worst_severity,
                matched_rules=_distinct_rules(report),
            )
        prepared = UntrustedContentPolicy.prepare(text, report, thresholds=thresholds)
        if prepared.action in {"quarantine", "reject"}:
            return UntrustedContentResult(
                action="mask",
                text=redact_findings(text, report.findings),
                worst_severity=prepared.worst_severity,
                matched_rules=prepared.matched_rules,
            )
        return prepared


def _distinct_rules(report: PromptInjectionReport) -> tuple[str, ...]:
    """Unique matched rule ids in first-match order (bounded audit metadata)."""
    seen: list[str] = []
    for finding in report.findings:
        if finding.rule not in seen:
            seen.append(finding.rule)
    return tuple(seen)


def budget_untrusted_text(text: str, *, max_chars: int) -> str:
    """Fit already-fenced untrusted text into a turn budget.

    Multi-attachment turns are budgeted **per fence**: head+tail on the joined
    blob used to drop the second file's header while keeping dialog history noise,
    so the model saw one document and asked for a "second" upload (055).
    Truncation always stays explicit — never a silent cut (020).
    """
    if max_chars < 64:
        raise ValueError("max_chars must be >= 64")
    if len(text) <= max_chars:
        return text
    blocks = _FENCE_BLOCK.findall(text)
    if len(blocks) >= 2:
        return _budget_multi_fences(blocks, max_chars=max_chars)
    return _budget_head_tail(text, max_chars=max_chars)


def _budget_multi_fences(blocks: list[str], *, max_chars: int) -> str:
    """Fair-share char budget across complete fences; omit trailing fences if needed."""
    sep = "\n\n"
    n = len(blocks)
    overhead = len(sep) * (n - 1)
    usable = max_chars - overhead
    if usable < 96:
        return _budget_head_tail(sep.join(blocks), max_chars=max_chars)

    per = max(96, usable // n)
    trimmed: list[str] = []
    used = 0
    for index, block in enumerate(blocks):
        piece = _shrink_fence_block(block, max_chars=per)
        extra = len(sep) if trimmed else 0
        if used + extra + len(piece) > max_chars and trimmed:
            omitted = n - index
            marker = f"\n… [{omitted} attachment fence(s) omitted — turn budget] …\n"
            if used + len(marker) <= max_chars:
                return sep.join(trimmed) + marker
            return sep.join(trimmed)
        if trimmed:
            used += len(sep)
        trimmed.append(piece)
        used += len(piece)
    joined = sep.join(trimmed)
    if len(joined) <= max_chars:
        return joined
    return _budget_head_tail(joined, max_chars=max_chars)


def _shrink_fence_block(block: str, *, max_chars: int) -> str:
    """Keep fence open/close; truncate body with an explicit marker."""
    if len(block) <= max_chars:
        return block
    open_match = _FENCE_OPEN.match(block)
    if open_match is None or not block.endswith(_FENCE_CLOSE):
        return _budget_head_tail(block, max_chars=max_chars)
    header = open_match.group(1)
    body = block[open_match.end() : -len(_FENCE_CLOSE)].strip("\n")
    marker = "\n… [attachment body truncated] …\n"
    fixed = len(header) + 1 + len(marker) + 1 + len(_FENCE_CLOSE)
    if max_chars <= fixed + 24:
        return _budget_head_tail(block, max_chars=max_chars)
    keep = (max_chars - fixed) // 2
    if len(body) > keep * 2:
        head = _cut_at_boundary(body, keep, from_end=False)
        tail = _cut_at_boundary(body, keep, from_end=True)
        new_body = f"{head}{marker}{tail}"
    else:
        new_body = _cut_at_boundary(body, max_chars - fixed, from_end=False)
    return f"{header}\n{new_body}\n{_FENCE_CLOSE}"


def _budget_head_tail(text: str, *, max_chars: int) -> str:
    omitted = len(text) - max_chars
    marker = f"\n… [attachment context truncated {omitted} chars] …\n"
    if max_chars <= len(marker) + 24:
        return _cut_at_boundary(text, max_chars, from_end=False)
    keep = (max_chars - len(marker)) // 2
    head = _cut_at_boundary(text, keep, from_end=False)
    tail = _cut_at_boundary(text, keep, from_end=True)
    return f"{head}{marker}{tail}"


def _cut_at_boundary(text: str, max_chars: int, *, from_end: bool) -> str:
    """Trim at whitespace when possible so mid-word cuts are rare."""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if from_end:
        piece = text[-max_chars:]
        space = piece.find(" ")
        if 0 <= space < max_chars // 2:
            return piece[space + 1 :]
        return piece
    piece = text[:max_chars]
    space = piece.rfind(" ")
    if space > max_chars // 2:
        return piece[:space].rstrip()
    return piece.rstrip()
