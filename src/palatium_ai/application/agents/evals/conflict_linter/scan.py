# src/palatium_ai/application/agents/evals/conflict_linter/scan.py

"""Same-prompt conflict scan over audit revisions and raw texts."""

from __future__ import annotations

from pathlib import Path

from palatium_ai.application.agents.evals.conflict_linter.models import (
    ConflictFinding,
    ConflictReport,
)
from palatium_ai.application.agents.evals.conflict_linter.noqa import nearest_noqa, noqa_map
from palatium_ai.application.agents.evals.conflict_linter.sections import (
    extract_string_literals,
    split_sections,
)
from palatium_ai.application.agents.evals.conflict_linter.static_rules import scan_section
from palatium_ai.application.agents.evals.prompt_revisions import AUDIT_PROMPT_REVISIONS

_REPO_ROOT = Path(__file__).resolve().parents[6]
_SRC = _REPO_ROOT / "src" / "palatium_ai"


def _apply_noqa(findings: list[ConflictFinding], source: str) -> list[ConflictFinding]:
    mapping = noqa_map(source)
    out: list[ConflictFinding] = []
    for item in findings:
        why = nearest_noqa(item.line_hint, mapping)
        if why is None:
            out.append(item)
            continue
        out.append(
            item.model_copy(
                update={
                    "suppressed": True,
                    "noqa_reason": why or "(missing why — still suppressed; add a reason)",
                }
            )
        )
    return out


def scan_text(
    text: str,
    *,
    path: str,
    prompt_id: str | None = None,
    line_base: int = 1,
    source_for_noqa: str | None = None,
) -> list[ConflictFinding]:
    """Scan one prompt body (fixture or extracted literal)."""
    findings: list[ConflictFinding] = []
    for section in split_sections(text):
        findings.extend(scan_section(section, path=path, prompt_id=prompt_id, line_base=line_base))
    return _apply_noqa(findings, source_for_noqa if source_for_noqa is not None else text)


def scan_python_source(path: Path, *, prompt_id: str | None = None) -> list[ConflictFinding]:
    """Scan large string literals inside a prompts module."""
    source = path.read_text(encoding="utf-8")
    rel = path.relative_to(_REPO_ROOT).as_posix() if path.is_relative_to(_REPO_ROOT) else path.as_posix()
    findings: list[ConflictFinding] = []
    for body, start_line in extract_string_literals(source):
        findings.extend(
            scan_text(
                body,
                path=rel,
                prompt_id=prompt_id,
                line_base=start_line,
                source_for_noqa=source,
            )
        )
    return findings


def scan_audit_revisions() -> ConflictReport:
    """Scan every file listed in ``AUDIT_PROMPT_REVISIONS`` (same-prompt only)."""
    findings: list[ConflictFinding] = []
    for revision in AUDIT_PROMPT_REVISIONS:
        path = _SRC / revision.relative_path
        findings.extend(scan_python_source(path, prompt_id=revision.prompt_id))
    return ConflictReport(
        findings=tuple(findings),
        scanned_files=len(AUDIT_PROMPT_REVISIONS),
        mode="same_prompt",
    )
