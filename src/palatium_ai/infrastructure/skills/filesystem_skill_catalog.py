# src/palatium_ai/infrastructure/skills/filesystem_skill_catalog.py

"""Filesystem SkillCatalogPort — progressive disclosure for L5 procedural skills."""

from __future__ import annotations

from pathlib import Path

from palatium_ai.core.logging import get_logger
from palatium_ai.domain.skills.frontmatter import is_safe_skill_name, parse_skill_frontmatter
from palatium_ai.domain.skills.types import SkillReference, SkillSummary

logger = get_logger(__name__)

class FilesystemSkillCatalog:
    """Scan ``SKILL.md`` trees; summaries for JIT, ``reference.md`` on demand."""

    def __init__(
        self,
        roots: tuple[str, ...] | list[str],
        *,
        reference_max_chars: int = 12_000,
        base_dir: Path | None = None,
    ) -> None:
        self._roots = tuple(str(r).strip() for r in roots if str(r).strip())
        self._reference_max_chars = max(500, int(reference_max_chars))
        self._base = (base_dir or Path.cwd()).resolve()
        self._by_name: dict[str, _SkillFiles] | None = None

    def list_summaries(self) -> tuple[SkillSummary, ...]:
        index = self._ensure_index()
        return tuple(
            SkillSummary(
                name=name,
                description=entry.description,
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
                _name, _desc, body = parse_skill_frontmatter(raw)
                content = body
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
                if not _path_under_root(skill_md, root):
                    continue
                if any(marker in skill_md.parts for marker in (".agent",)):
                    continue
                try:
                    raw = skill_md.read_text(encoding="utf-8")
                    name, description, _body = parse_skill_frontmatter(raw)
                except (OSError, ValueError) as exc:
                    logger.warning(
                        "skill_catalog.skip_invalid",
                        path=str(skill_md),
                        error=str(exc),
                    )
                    continue
                ref = skill_md.parent / "reference.md"
                entry = _SkillFiles(
                    description=description,
                    skill_path=skill_md,
                    reference_path=ref if ref.is_file() else None,
                )
                if name in out:
                    # G9 lite: curator refuses silent overwrite — keep first, warn.
                    logger.warning(
                        "skill_catalog.duplicate_name",
                        name=name,
                        kept=str(out[name].skill_path),
                        skipped=str(skill_md),
                    )
                    continue
                out[name] = entry
        return out


class _SkillFiles:
    __slots__ = ("description", "reference_path", "skill_path")

    def __init__(
        self,
        *,
        description: str,
        skill_path: Path,
        reference_path: Path | None,
    ) -> None:
        self.description = description
        self.skill_path = skill_path
        self.reference_path = reference_path


def _path_under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _is_forbidden_root(root: Path) -> bool:
    """Reject `.agent/**` roots — Cursor DX MEMORY.md is never product L5."""
    return ".agent" in {p.lower() for p in root.parts}
