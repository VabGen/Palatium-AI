# src/palatium_ai/domain/skills/lint.py

"""Deterministic safety lint for self-authored SKILL.md (CMD4 / 070)."""

from __future__ import annotations

import re

from pydantic import BaseModel

from palatium_ai.core.security.secret_scanner import SecretScanError, scan_text
from palatium_ai.domain.skills.frontmatter import ParsedSkillFrontmatter, parse_skill_frontmatter

#: Hard cap on body after frontmatter (prompt-injection surface).
SKILL_BODY_MAX_CHARS = 20_000
SKILL_CONTENT_MAX_CHARS = 30_000

_IC = re.IGNORECASE

# Shell / process escape — reject before any filesystem write.
_DANGEROUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("rm -rf / destructive delete", re.compile(r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*r|-rf|-fr)\b", _IC)),
    ("curl|wget piped to shell", re.compile(r"\b(curl|wget)\b[^\n]{0,200}\|\s*(ba)?sh\b", _IC)),
    ("os.system", re.compile(r"\bos\.system\s*\(")),
    ("subprocess", re.compile(r"\bsubprocess\.(run|Popen|call|check_output)\s*\(")),
    ("eval/exec", re.compile(r"\b(eval|exec)\s*\(")),
    ("__import__", re.compile(r"\b__import__\s*\(")),
    ("powershell encoded command", re.compile(r"\bpowershell\b[^\n]{0,80}-enc(odedcommand)?\b", _IC)),
    ("bash -c with pipe", re.compile(r"\b(ba)?sh\s+-c\b[^\n]{0,120}\|", _IC)),
)

# Prompt-injection / agent hijack heuristics (case-insensitive).
_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore prior instructions",
        re.compile(r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+instructions?", _IC),
    ),
    ("system prompt override", re.compile(r"\b(system\s+prompt|jailbreak)\b", _IC)),
    ("reveal hidden prompt", re.compile(r"\b(reveal|dump|print)\s+(your|the)\s+(system\s+)?prompt\b", _IC)),
    ("you are now role-swap", re.compile(r"\byou\s+are\s+now\b.{0,40}\b(unrestricted|admin|root)\b", _IC)),
    ("disable safety", re.compile(r"\b(disable|bypass)\s+(all\s+)?(safety|guardrails?|hitl)\b", _IC)),
)


class SkillLintResult(BaseModel):
    """Outcome of ``lint_skill_markdown`` — never raises for policy rejects."""

    model_config = {"frozen": True}

    ok: bool
    errors: tuple[str, ...] = ()
    name: str = ""
    description: str = ""
    version: str = ""


def lint_skill_markdown(
    raw: str,
    *,
    expected_name: str | None = None,
    expected_description: str | None = None,
) -> SkillLintResult:
    """Validate frontmatter + ban dangerous / injection patterns (CMD4.1).

    Returns ``ok=False`` with human-readable ``errors`` — never raises for lint
    rejects (callers map to MCP error). Programming bugs still raise.
    """
    text = (raw or "").replace("\r\n", "\n")
    size_error = _content_size_error(text)
    if size_error is not None:
        return SkillLintResult(ok=False, errors=(size_error,))

    try:
        parsed = parse_skill_frontmatter(text)
    except ValueError as exc:
        return SkillLintResult(ok=False, errors=(str(exc),))

    errors = _collect_policy_errors(
        text,
        parsed,
        expected_name=expected_name,
        expected_description=expected_description,
    )
    return SkillLintResult(
        ok=not errors,
        errors=tuple(errors),
        name=parsed.name,
        description=parsed.description,
        version=parsed.version,
    )


def _content_size_error(text: str) -> str | None:
    if not text.strip():
        return "content is required"
    if len(text) > SKILL_CONTENT_MAX_CHARS:
        return f"content exceeds {SKILL_CONTENT_MAX_CHARS} characters"
    return None


def _collect_policy_errors(
    text: str,
    parsed: ParsedSkillFrontmatter,
    *,
    expected_name: str | None,
    expected_description: str | None,
) -> list[str]:
    errors: list[str] = []
    if expected_name and parsed.name != expected_name.strip():
        errors.append(f"frontmatter.name '{parsed.name}' does not match skill_name '{expected_name.strip()}'")
    wanted_desc = (expected_description or "").strip()
    if wanted_desc and parsed.description != wanted_desc:
        errors.append("frontmatter.description does not match description argument")
    if len(parsed.body) > SKILL_BODY_MAX_CHARS:
        errors.append(f"skill body exceeds {SKILL_BODY_MAX_CHARS} characters")
    errors.extend(_match_patterns(text, _DANGEROUS_PATTERNS, prefix="dangerous pattern rejected"))
    errors.extend(_match_patterns(text, _INJECTION_PATTERNS, prefix="injection pattern rejected"))
    try:
        scan_text(text, field="skill_content")
    except SecretScanError as exc:
        errors.append(str(exc))
    return errors


def _match_patterns(
    text: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
    *,
    prefix: str,
) -> list[str]:
    return [f"{prefix}: {label}" for label, pattern in patterns if pattern.search(text)]


__all__ = [
    "SKILL_BODY_MAX_CHARS",
    "SKILL_CONTENT_MAX_CHARS",
    "SkillLintResult",
    "lint_skill_markdown",
]
