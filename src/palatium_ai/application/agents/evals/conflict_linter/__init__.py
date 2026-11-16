# src/palatium_ai/application/agents/evals/conflict_linter/__init__.py

"""Prompt conflict-linter (same-prompt v1) — backlog §2."""

from palatium_ai.application.agents.evals.conflict_linter.fixtures import (
    fixture_metrics,
    load_manifest,
    run_fixture_suite,
)
from palatium_ai.application.agents.evals.conflict_linter.models import ConflictFinding, ConflictReport
from palatium_ai.application.agents.evals.conflict_linter.scan import scan_audit_revisions, scan_text

__all__ = [
    "ConflictFinding",
    "ConflictReport",
    "fixture_metrics",
    "load_manifest",
    "run_fixture_suite",
    "scan_audit_revisions",
    "scan_text",
]
