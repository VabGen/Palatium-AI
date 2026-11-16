# src/palatium_ai/infrastructure/skills/filesystem_skill_catalog.py

"""Filesystem SkillCatalogPort — progressive disclosure for L5 procedural skills."""

from __future__ import annotations

import shutil

from pathlib import Path

from palatium_ai.core.logging import get_logger
from palatium_ai.domain.skills.frontmatter import is_safe_skill_name, parse_skill_frontmatter
from palatium_ai.domain.skills.product_lock import (
    load_product_lock,
    remove_lock_entry,
    upsert_lock_entry,
    write_product_lock,
)
from palatium_ai.domain.skills.types import SkillReference, SkillSummary

logger = get_logger(__name__)


class FilesystemSkillCatalog:
    """Scan ``SKILL.md`` trees; summaries for JIT, ``reference.md`` on demand.

    Index is cached until ``invalidate_index`` / ``upsert_skill`` / ``delete_skill``.
    Manual edits outside ``skill_manage`` still need a process restart (or invalidate).
    """

    def __init__(
        self,
        roots: tuple[str, ...] | list[str],
        *,
        reference_max_chars: int = 12_000,
        base_dir: Path | None = None,
        product_lock_path: str | Path | None = None,
        write_root: str | None = None,
    ) -> None:
        self._roots = tuple(str(r).strip() for r in roots if str(r).strip())
        self._reference_max_chars = max(500, int(reference_max_chars))
        self._base = (base_dir or Path.cwd()).resolve()
        self._by_name: dict[str, _SkillFiles] | None = None
        lock_raw = product_lock_path or "skills/procedural/skills-lock.json"
        lock_path = Path(str(lock_raw))
        self._lock_path = (self._base / lock_path).resolve() if not lock_path.is_absolute() else lock_path.resolve()
        # Writes confined to the first root (or explicit write_root).
        wr = (write_root or (self._roots[0] if self._roots else "skills/procedural")).strip()
        wr_path = Path(wr)
        self._write_root = (self._base / wr_path).resolve() if not wr_path.is_absolute() else wr_path.resolve()

    def list_summaries(self) -> tuple[SkillSummary, ...]:
        index = self._ensure_index()
        return tuple(
            SkillSummary(
                name=name,
                description=entry.description,
                version=entry.version,
                has_reference=entry.reference_path is not None,
            )
            for name, entry in sorted(index.items(), key=lambda item: item[0])
        )

    def get_reference(self, name: str) -> SkillReference | None:
        safe = name.strip()
        if not is_safe_skill_name(safe):
            return None
        entry = self._ensure_index().get(safe)
        if entry is None:
            return None
        path = entry.reference_path or entry.skill_path
        kind = "reference" if entry.reference_path is not None else "skill_body"
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("skill_catalog.read_failed", name=safe, error=str(exc))
            return None
        if path == entry.skill_path:
            try:
                parsed = parse_skill_frontmatter(raw)
                content = parsed.body
            except ValueError:
                content = raw
        else:
            content = raw
        truncated = len(content) > self._reference_max_chars
        if truncated:
            content = content[: self._reference_max_chars]
        return SkillReference(name=safe, kind=kind, content=content, truncated=truncated)

    def format_catalog(self, *, max_chars: int) -> str:
        """Compact level-1 catalog for ContextBuilder (never full bodies)."""
        lines: list[str] = []
        used = 0
        budget = max(200, int(max_chars))
        for summary in self.list_summaries():
            ref = " [+ref]" if summary.has_reference else ""
            line = f"- {summary.name}{ref}: {summary.description}"
            if used + len(line) + 1 > budget:
                break
            lines.append(line)
            used += len(line) + 1
        if not lines:
            return "(no procedural skills)"
        return "Procedural skills (call skill_reference for details):\n" + "\n".join(lines)

    def invalidate_index(self) -> None:
        """Drop cached index so the next read rescans the filesystem."""
        self._by_name = None

    def upsert_skill(self, *, name: str, content: str) -> SkillSummary:
        """Atomically write ``<write_root>/<name>/SKILL.md`` and update product lock."""
        safe = name.strip()
        if not is_safe_skill_name(safe):
            msg = f"unsafe skill name: {name!r}"
            raise ValueError(msg)
        if _is_forbidden_root(self._write_root):
            msg = f"write root forbidden: {self._write_root}"
            raise ValueError(msg)
        parsed = parse_skill_frontmatter(content)
        if parsed.name != safe:
            msg = f"frontmatter.name '{parsed.name}' must equal skill name '{safe}'"
            raise ValueError(msg)

        skill_dir = (self._write_root / safe).resolve()
        if not _path_under_root(skill_dir, self._write_root):
            msg = "skill path escapes write root"
            raise ValueError(msg)
        skill_dir.mkdir(parents=True, exist_ok=True)
        target = skill_dir / "SKILL.md"
        tmp = skill_dir / "SKILL.md.tmp"
        normalized = content.replace("\r\n", "\n")
        if not normalized.endswith("\n"):
            normalized += "\n"
        tmp.write_text(normalized, encoding="utf-8")
        # Re-parse temp file before replace (defense in depth).
        parse_skill_frontmatter(tmp.read_text(encoding="utf-8"))
        tmp.replace(target)

        lock = load_product_lock(self._lock_path)
        lock = upsert_lock_entry(lock, name=safe, version=parsed.version, content=normalized)
        write_product_lock(self._lock_path, lock)
        self.invalidate_index()
        logger.info("skill_catalog.upserted", name=safe, version=parsed.version)
        return SkillSummary(
            name=safe,
            description=parsed.description,
            version=parsed.version,
            has_reference=(skill_dir / "reference.md").is_file(),
        )

    def delete_skill(self, *, name: str) -> bool:
        """Remove ``<write_root>/<name>/`` when present; update product lock."""
        safe = name.strip()
        if not is_safe_skill_name(safe):
            msg = f"unsafe skill name: {name!r}"
            raise ValueError(msg)
        skill_dir = (self._write_root / safe).resolve()
        if not _path_under_root(skill_dir, self._write_root):
            msg = "skill path escapes write root"
            raise ValueError(msg)
        if skill_dir == self._write_root.resolve():
            msg = "refusing to delete write root"
            raise ValueError(msg)
        if not skill_dir.is_dir():
            return False
        shutil.rmtree(skill_dir)
        lock = load_product_lock(self._lock_path)
        lock = remove_lock_entry(lock, name=safe)
        write_product_lock(self._lock_path, lock)
        self.invalidate_index()
        logger.info("skill_catalog.deleted", name=safe)
        return True

    def _ensure_index(self) -> dict[str, _SkillFiles]:
        if self._by_name is None:
            self._by_name = self._scan()
        return self._by_name

    def _scan(self) -> dict[str, _SkillFiles]:
        out: dict[str, _SkillFiles] = {}
        for root_raw in self._roots:
            root = Path(root_raw)
            root = (self._base / root).resolve() if not root.is_absolute() else root.resolve()
            if not root.is_dir():
                logger.info("skill_catalog.root_missing", root=str(root))
                continue
            if _is_forbidden_root(root):
                logger.warning("skill_catalog.root_forbidden", root=str(root))
                continue
            for skill_md in sorted(root.rglob("SKILL.md")):
                _ingest_skill_md(skill_md, root=root, out=out)
        return out


class _SkillFiles:
    __slots__ = ("description", "reference_path", "skill_path", "version")

    def __init__(
        self,
        *,
        description: str,
        version: str,
        skill_path: Path,
        reference_path: Path | None,
    ) -> None:
        self.description = description
        self.version = version
        self.skill_path = skill_path
        self.reference_path = reference_path


def _ingest_skill_md(
    skill_md: Path,
    *,
    root: Path,
    out: dict[str, _SkillFiles],
) -> None:
    if not _path_under_root(skill_md, root):
        return
    if any(marker in skill_md.parts for marker in (".agent",)):
        return
    parent = skill_md.parent.resolve()
    if parent == root.resolve():
        logger.warning(
            "skill_catalog.skip_root_skill_md",
            path=str(skill_md),
            reason="SKILL.md must live in a per-skill subdirectory",
        )
        return
    try:
        raw = skill_md.read_text(encoding="utf-8")
        parsed = parse_skill_frontmatter(raw)
    except (OSError, ValueError) as exc:
        logger.warning(
            "skill_catalog.skip_invalid",
            path=str(skill_md),
            error=str(exc),
        )
        return
    if parent.name != parsed.name:
        logger.warning(
            "skill_catalog.skip_name_mismatch",
            path=str(skill_md),
            folder=parent.name,
            name=parsed.name,
        )
        return
    ref = parent / "reference.md"
    entry = _SkillFiles(
        description=parsed.description,
        version=parsed.version,
        skill_path=skill_md,
        reference_path=ref if ref.is_file() else None,
    )
    if parsed.name in out:
        # G9 lite: curator refuses silent overwrite — keep first, warn.
        logger.warning(
            "skill_catalog.duplicate_name",
            name=parsed.name,
            kept=str(out[parsed.name].skill_path),
            skipped=str(skill_md),
        )
        return
    out[parsed.name] = entry


def _path_under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _is_forbidden_root(root: Path) -> bool:
    """Reject `.agent/**` roots — Cursor DX MEMORY.md is never product L5."""
    return ".agent" in {p.lower() for p in root.parts}
