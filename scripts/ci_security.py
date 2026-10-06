#!/usr/bin/env python
"""CI supply-chain baseline: lockfile, action pins, base images, dependency audit (SCA).

Four blocking gates, cheapest first (rule 025):

1. ``poetry check --lock`` — the lockfile must match ``pyproject.toml``. A drifted
   lock means CI installs something other than what was reviewed.
2. Action pin drift — every third-party ``uses:`` in ``.github/workflows`` must be
   pinned to a commit SHA carrying its release version. A mutable tag would let
   upstream change the code we execute without a pull request in this repo.
3. Base image pin drift — every external ``FROM`` in a Dockerfile must be pinned by
   digest. Same reasoning as (2), one layer down: ``python:3.14-slim`` is a moving tag.
4. ``pip-audit`` against the installed environment. A known vulnerable dependency
   must be triaged, not ignored silently.

Triaged advisories go into ``security/pip-audit-ignore.txt`` — one advisory ID per
line, ``#`` comments allowed. Every entry is an explicit, reviewable decision.

Static-analysis (bandit) rules are already enforced by ruff's ``S`` selector in
``scripts/ci_quality.py``; running a second tool for the same class of findings would
be duplicate tooling (050).
"""

from __future__ import annotations

import re
import subprocess
import sys

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_IGNORE_FILE = _ROOT / "security" / "pip-audit-ignore.txt"
_WORKFLOWS = _ROOT / ".github" / "workflows"

# `uses: owner/repo@<ref>` — optional leading `- `, optional quotes.
_USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*['\"]?(?P<target>[^\s'\"]+)")
# A commit SHA, not a tag: 40 lowercase hex characters.
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# The version comment dependabot needs to map a pin back to a release.
_VERSION_COMMENT_RE = re.compile(r"#\s*v?\d+(?:\.\d+)*\s*$")
# `FROM <image> [AS <stage>]` — the image ref is everything before whitespace.
_FROM_RE = re.compile(r"^\s*FROM\s+(?P<image>[^\s]+)", re.IGNORECASE)
_AS_STAGE_RE = re.compile(r"\sAS\s+(?P<stage>[^\s]+)\s*$", re.IGNORECASE)
# `repo/name:tag@sha256:<64 hex>` or `repo/name@sha256:<64 hex>`.
_IMAGE_DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")
# Stage names are not registry images; these trees are other teams' files (017, 090).
_EXCLUDED_PARTS = frozenset({"node_modules", ".venv", "venv", "JavaEdms", "edms-ai-assistant"})


def _load_ignored_vulns() -> list[str]:
    """Advisory IDs explicitly triaged as accepted risk."""
    if not _IGNORE_FILE.exists():
        return []
    ids: list[str] = []
    for line in _IGNORE_FILE.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            ids.append(entry)
    return ids


def check_lockfile() -> None:
    """Fail if ``poetry.lock`` is out of sync with ``pyproject.toml`` (rule 025)."""
    print("== poetry check --lock ==")
    # `poetry` resolves through PATH on purpose: CI installs it with pipx, and a
    # hardcoded venv path would break on a developer machine.
    completed = subprocess.run(
        ["poetry", "check", "--lock"],  # noqa: S607  # PATH-resolved interpreter wrapper
        cwd=_ROOT,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def unpinned_actions() -> list[str]:
    """Workflow ``uses:`` refs that are neither local nor SHA-pinned with a version."""
    offenders: list[str] = []
    for path in sorted(_WORKFLOWS.glob("*.y*ml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            match = _USES_RE.match(line)
            if match is None:
                continue
            target = match.group("target")
            if target.startswith("./"):
                continue  # local composite action: nothing upstream to pin
            _, _, ref = target.partition("@")
            if not _SHA_RE.match(ref) or _VERSION_COMMENT_RE.search(line) is None:
                offenders.append(f"{path.relative_to(_ROOT).as_posix()}:{lineno}: {target}")
    return offenders


def check_action_pins() -> None:
    """Fail if a third-party action is referenced by a mutable tag (rule 025)."""
    print("== action pin drift ==")
    offenders = unpinned_actions()
    if offenders:
        print("pin by commit SHA with a version comment, e.g. `@<sha> # v4.4.0`:")
        for offender in offenders:
            print(f"  {offender}")
        raise SystemExit(1)
    print("all third-party actions are SHA-pinned")


def iter_dockerfiles(root: Path) -> list[Path]:
    """Every Dockerfile worth checking, vendor trees excluded (017, 090)."""
    found = [
        path
        for path in root.rglob("Dockerfile*")
        if path.is_file() and not any(part in _EXCLUDED_PARTS for part in path.relative_to(root).parts)
    ]
    return sorted(found)


def unpinned_base_images(root: Path | None = None) -> list[str]:
    """``FROM`` refs that are neither a build stage nor digest-pinned.

    Stage references (``FROM base``) and ``scratch`` resolve inside the file, so there is
    nothing upstream to pin. Everything else must carry ``@sha256:<64 hex>``; a purely
    parameterised ref (``FROM ${BASE_IMAGE}``) cannot be verified statically and is
    reported rather than trusted — that form is the mutable-tag escape hatch.
    """
    base = root or _ROOT
    offenders: list[str] = []
    for path in iter_dockerfiles(base):
        stages: set[str] = set()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = _FROM_RE.match(line)
            if match is None:
                continue
            image = match.group("image")
            stage = _AS_STAGE_RE.search(line)
            if stage is not None:
                stages.add(stage.group("stage").lower())
            if image.lower() in stages or image.lower() == "scratch":
                continue
            if _IMAGE_DIGEST_RE.search(image) is None:
                offenders.append(f"{path.relative_to(base).as_posix()}:{lineno}: {image}")
    return offenders


def check_base_image_pins() -> None:
    """Fail if a Dockerfile builds from a mutable tag instead of a digest (rule 025)."""
    print("== base image pin drift ==")
    offenders = unpinned_base_images()
    if offenders:
        print("pin by digest with the tag kept as a hint, e.g. `python:3.14-slim@sha256:<64 hex>`:")
        for offender in offenders:
            print(f"  {offender}")
        raise SystemExit(1)
    print("all Dockerfile base images are digest-pinned")


def check_dependency_audit() -> None:
    """Fail on untriaged vulnerable dependencies (blocking SCA gate)."""
    ignored = _load_ignored_vulns()
    # `--skip-editable`: this project is installed editable and is not published to
    # PyPI, so pip-audit's lookup for it always 404s/503s on the index. Without the
    # flag a transient index hiccup fails the gate for no security reason; the
    # project's own code is not an SCA target anyway (see rule 040/050).
    argv = ["poetry", "run", "pip-audit", "--skip-editable"]
    for vuln_id in ignored:
        argv += ["--ignore-vuln", vuln_id]

    print("== pip-audit (SCA) ==")
    if ignored:
        print(f"triaged (accepted risk): {', '.join(ignored)}")
    else:
        print(f"no triaged advisories ({_IGNORE_FILE.relative_to(_ROOT).as_posix()} is empty)")

    completed = subprocess.run(argv, cwd=_ROOT, check=False)  # noqa: S603
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> int:
    """Run every supply-chain gate; non-zero on the first failure."""
    check_lockfile()
    check_action_pins()
    check_base_image_pins()
    check_dependency_audit()
    print("ci_security: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
