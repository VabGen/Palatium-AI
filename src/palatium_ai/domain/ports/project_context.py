# src/palatium_ai/domain/ports/project_context.py

"""Project operating-contract files (AGENTS.md) — filesystem, not medium memory."""

from __future__ import annotations

from typing import Protocol


class ProjectContextPort(Protocol):
    """Load allowlisted project context for JIT stable-tier injection (CMD2)."""

    def load_agents_md(self) -> str:
        """Return AGENTS.md body (capped) or empty string when missing/disabled."""
        ...

    def agents_md_content_hash(self) -> str:
        """Stable hex digest of the loaded body (empty when absent)."""
        ...
