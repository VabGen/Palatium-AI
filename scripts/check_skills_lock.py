#!/usr/bin/env python3
"""Warn-only drift check for product ``skills/procedural/skills-lock.json`` (CMD4).

Exit 0 always unless ``--strict`` is passed (then drift → exit 1).
DX ``skills-lock.json`` at repo root is intentionally ignored.
"""

from __future__ import annotations

import argparse
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from palatium_ai.domain.skills.frontmatter import parse_skill_frontmatter  # noqa: E402
from palatium_ai.domain.skills.product_lock import content_sha256, load_product_lock  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lock",
        default="skills/procedural/skills-lock.json",
        help="Path to product skills-lock.json",
    )
    parser.add_argument(
        "--root",
        default="skills/procedural",
        help="Procedural skills root to scan",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on drift (default: warn-only, exit 0)",
    )
    args = parser.parse_args()
    lock_path = (ROOT / args.lock).resolve()
    skill_root = (ROOT / args.root).resolve()
    lock = load_product_lock(lock_path)

    drift: list[str] = []
    on_disk: set[str] = set()
    for skill_md in sorted(skill_root.glob("*/SKILL.md")):
        name = skill_md.parent.name
        on_disk.add(name)
        raw = skill_md.read_text(encoding="utf-8")
        try:
            parsed = parse_skill_frontmatter(raw)
        except ValueError as exc:
            drift.append(f"{name}: invalid SKILL.md ({exc})")
            continue
        digest = content_sha256(raw)
        entry = lock.skills.get(name)
        if entry is None:
            drift.append(f"{name}: missing from lock (version={parsed.version})")
            continue
        if entry.sha256 != digest:
            drift.append(f"{name}: sha256 drift (lock={entry.sha256[:12]}… disk={digest[:12]}…)")
        if entry.version != parsed.version:
            drift.append(f"{name}: version drift (lock={entry.version} disk={parsed.version})")

    drift.extend(f"{name}: in lock but SKILL.md missing on disk" for name in sorted(set(lock.skills) - on_disk))

    if not drift:
        print(f"skills-lock OK ({len(on_disk)} skills) — {lock_path.relative_to(ROOT)}")
        return 0

    print("skills-lock drift:")
    for line in drift:
        print(f"  - {line}")
    if args.strict:
        return 1
    print("(warn-only; pass --strict to fail)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
