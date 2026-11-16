"""Deterministic user-facing lint for ``ContentDocument`` (W0a).

Imported explicitly (``from palatium_ai.domain.content.lint import ContentLint``),
not re-exported from ``palatium_ai.domain.content``: the rule set depends on
``domain.policies.internal_vocabulary``, which itself imports ``domain.content`` —
re-exporting here would close that cycle at package import time.
"""

from palatium_ai.domain.content.lint.engine import ContentLint
from palatium_ai.domain.content.lint.models import (
    LintFinding,
    LintReport,
    LintRuleId,
    LintSeverity,
)

__all__ = ["ContentLint", "LintFinding", "LintReport", "LintRuleId", "LintSeverity"]
