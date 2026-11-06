# src/palatium_ai/infrastructure/project_context/filesystem_agents_md.py

"""Filesystem ProjectContextPort — AGENTS.md with process-level cache (CMD2)."""

from __future__ import annotations

import hashlib

from pathlib import Path

from palatium_ai.core.logging import get_logger

logger = get_logger(__name__)

#: v1 allowlist: basename only (no path traversal into .agent/ or skills trees).
_ALLOWED_BASENAMES: frozenset[str] = frozenset({"AGENTS.md"})


class FilesystemAgentsMdLoader:
    """Read ``AGENTS.md`` once per (path, mtime); missing file → empty string."""

    def __init__(
        self,
        *,
        relative_path: str = "AGENTS.md",
        max_chars: int = 8_000,
        enabled: bool = True,
        base_dir: Path | None = None,
    ) -> None:
        self._enabled = enabled
        self._max_chars = max(500, int(max_chars))
        self._base = (base_dir or Path.cwd()).resolve()
        self._relative = relative_path.strip() or "AGENTS.md"
        self._cached_body: str | None = None
        self._cached_mtime_ns: int | None = None
        self._cached_hash: str = ""

    def load_agents_md(self) -> str:
        if not self._enabled:
            return ""
        path = self._resolved_path()
        if path is None:
            return ""
        try:
            stat = path.stat()
        except OSError:
            self._cached_body = ""
            self._cached_mtime_ns = None
            self._cached_hash = ""
            return ""
        if self._cached_body is not None and self._cached_mtime_ns == stat.st_mtime_ns:
            return self._cached_body
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("project_context.agents_md_read_failed", path=str(path), error=str(exc)[:200])
            self._cached_body = ""
            self._cached_mtime_ns = None
            self._cached_hash = ""
            return ""
        body = raw.strip()
        truncated = len(body) > self._max_chars
        if truncated:
            body = body[: self._max_chars]
            logger.info(
                "project_context.agents_md_truncated",
                path=str(path),
                max_chars=self._max_chars,
            )
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        self._cached_body = body
        self._cached_mtime_ns = stat.st_mtime_ns
        self._cached_hash = digest
        return body

    def agents_md_content_hash(self) -> str:
        self.load_agents_md()
        return self._cached_hash

    def _resolved_path(self) -> Path | None:
        candidate = Path(self._relative)
        path = candidate if candidate.is_absolute() else (self._base / candidate)
        try:
            resolved = path.resolve()
        except OSError:
            return None
        if resolved.name not in _ALLOWED_BASENAMES:
            logger.warning(
                "project_context.agents_md_basename_denied",
                name=resolved.name,
            )
            return None
        if not resolved.is_file():
            return None
        return resolved


__all__ = ["FilesystemAgentsMdLoader"]
