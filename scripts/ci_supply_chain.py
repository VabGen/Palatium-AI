#!/usr/bin/env python
"""Supply-chain gates for the release artefact: image scan, SBOM, keyless signature.

Deliberately separate from ``scripts/ci_security.py`` (025): that one is static and finishes
in seconds (lock, action/base-image pins, SCA), while this one needs Docker and Trivy's
vulnerability database. Two gates, two timeouts — a slow scanner must not hold back a fast
static failure, and running the static gate locally must not require Docker.

What runs here, in order:

1. ``docker build --target runtime`` — an artefact that does not build cannot be scanned.
2. ``trivy image`` — one JSON pass over the saved image, triage file applied, pip's vendored
   bundle skipped. ``--exit-code`` stays 0 on purpose: severity alone is not the gate.
3. The gate is **code** (``fixable_findings``): a HIGH/CRITICAL finding with a published fix
   fails the build. ``python:3.14-slim`` carries 40+ HIGH findings for which Debian has no
   fixed version at all, so blocking on severity — or hiding the rest with ``--ignore-unfixed``
   — would either disable the gate in a week or blind it (082). Deciding here keeps the report
   honest (what the gate lets through is visible in ``artifacts/trivy-report.json``) and makes
   the rule unit-testable without Docker.
4. SBOM of the same image — CycloneDX into ``artifacts/sbom.cdx.json``. The SBOM describes the
   artefact we ship (OS packages plus the venv built from ``uv.lock``), not the repository:
   a component inventory of the release is what a consumer can actually check.
5. ``--sign`` (CI only) — keyless ``cosign sign-blob`` over the SBOM, immediately followed by
   ``cosign verify-blob`` against this workflow's own identity. A signature nobody verifies is
   decoration; the verify step is what turns keyless signing into a gate that can fail.

Trivy is pulled as a digest-pinned OCI image and ``cosign`` comes from sigstore's installer
action (SHA-pinned, 025): adding another third-party GitHub Action inside the job that guards
the supply chain would widen the surface this gate exists to protect.

Accepted risks live in ``security/trivy-ignore.txt`` (``--ignorefile``), one ID per line with
an optional ``exp:<YYYY-MM-DD>`` suffix — an entry whose review date has passed stops being
honoured, so acceptance cannot silently become permanent.

Local use (stdlib-only, so ``--no-project`` keeps it out of the project venv)::

    uv run --no-project python scripts/ci_supply_chain.py              # build + scan + SBOM
    uv run --no-project python scripts/ci_supply_chain.py --no-build   # reuse palatium-ai:ci-scan already built

``--sign`` is intentionally unusable outside GitHub Actions: keyless signing needs the
runner's OIDC identity, and an unauthenticated signature would be meaningless.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_ARTIFACTS = _ROOT / "artifacts"
_IGNORE_FILE = _ROOT / "security" / "trivy-ignore.txt"
_IMAGE_TAG = "palatium-ai:ci-scan"
_IMAGE_TAR = _ARTIFACTS / "palatium-ai-ci-scan.tar"
_SBOM_PATH = _ARTIFACTS / "sbom.cdx.json"
_BUNDLE_PATH = _ARTIFACTS / "sbom.cdx.json.sigstore.json"
_REPORT_PATH = _ARTIFACTS / "trivy-report.json"

# Trivy 0.76.0 (index digest) — the scanner that produces both the gate and the SBOM. Pin by
# digest, tag as the human hint (025). Bump via a reviewable PR; `--version` in CI logs tells
# which scanner produced a report.
TRIVY_IMAGE = "aquasec/trivy:0.76.0@sha256:2416d1f74045b57274df1a340eee6b510cacd73c66a6ccb8da092b117eb7d222"

_DIGEST_PIN_RE = re.compile(r"@sha256:[0-9a-f]{64}$")
#: Mount point of the repository inside the tool container.
_SCAN_MOUNT = "/scan"
_SEVERITIES = {"HIGH", "CRITICAL"}
_SBOM_FORMAT = "cyclonedx"
#: Trivy's own default is 5 minutes, and analysing the saved image routinely takes longer than
#: that on a laptop — the first real run died on ``context deadline exceeded``. The timeout is
#: per Trivy invocation, so the CI job budget (30 min) still has room for build + SBOM + signing.
_SCAN_TIMEOUT = "15m"
_GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"

#: pip vendors its own copies of msgpack/urllib3/setuptools and records them in
#: ``pip/_vendor/vendor.txt``; Trivy reads that file and reports them as installed
#: distributions, although the image has no matching ``dist-info`` and ``import urllib3``
#: fails in it. The application cannot reach them: it runs ``/app/.venv/bin/python``, whose
#: site-packages are populated only from ``uv.lock`` — and that set is pip-audit's blocking
#: job (025). Skipped by directory rather than triaged, because an entry in the triage file
#: would claim a risk that does not exist.
_VENDORED_SKIP_DIRS = ("**/pip/_vendor/**",)


def assert_digest_pinned(image: str) -> None:
    """Fail closed if a tool image is referenced by a mutable tag (025)."""
    if _DIGEST_PIN_RE.search(image) is None:
        raise SystemExit(f"tool image is not digest-pinned: {image}")


def repo_mount() -> str:
    """Repository path in the form Docker needs (forward slashes, no trailing separator)."""
    return str(_ROOT).replace("\\", "/")


def container_path(path: Path) -> str:
    """Path of a repository file as seen from inside the tool container."""
    return f"{_SCAN_MOUNT}/{path.relative_to(_ROOT).as_posix()}"


def display_path(path: Path) -> str:
    """Repo-relative path for logs, falling back to the absolute one outside the repo.

    ``relative_to`` raises on a path outside the root, and a gate that crashes with
    ``ValueError`` while reporting a missing file hides the message the operator needs.
    """
    try:
        return path.relative_to(_ROOT).as_posix()
    except ValueError:
        return str(path)


def _docker_run(mount: str) -> list[str]:
    """Prefix of every Trivy invocation: digest-pinned image with the repo mounted."""
    return ["docker", "run", "--rm", "-v", f"{mount}:{_SCAN_MOUNT}", TRIVY_IMAGE]


def trivy_scan_argv(mount: str) -> list[str]:
    """Argv for the image scan: JSON report for the whole image, triage and vendor policy applied.

    ``--exit-code 0`` because the decision is made by ``fixable_findings``, not by the scanner:
    Trivy cannot tell "a fix exists and we have not taken it" from "upstream has no fix".
    """
    return [
        *_docker_run(mount),
        "image",
        "--input",
        container_path(_IMAGE_TAR),
        "--scanners",
        "vuln",
        "--severity",
        ",".join(sorted(_SEVERITIES)),
        "--ignorefile",
        container_path(_IGNORE_FILE),
        "--skip-dirs",
        ",".join(_VENDORED_SKIP_DIRS),
        "--timeout",
        _SCAN_TIMEOUT,
        "--format",
        "json",
        "--output",
        container_path(_REPORT_PATH),
        "--exit-code",
        "0",
    ]


def trivy_sbom_argv(mount: str) -> list[str]:
    """Argv producing the CycloneDX SBOM of the image under scan."""
    return [
        *_docker_run(mount),
        "image",
        "--input",
        container_path(_IMAGE_TAR),
        "--skip-dirs",
        ",".join(_VENDORED_SKIP_DIRS),
        "--timeout",
        _SCAN_TIMEOUT,
        "--format",
        _SBOM_FORMAT,
        "--output",
        container_path(_SBOM_PATH),
    ]


def _objects(value: object) -> list[Mapping[str, Any]]:
    """The object items of a JSON array, tolerating a missing or malformed section."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def fixable_findings(report: Mapping[str, Any]) -> list[str]:
    """HIGH/CRITICAL findings that carry a published fix — the only actionable ones.

    A finding without ``FixedVersion`` is a gap in the base distribution, not a PR comment:
    it cannot be fixed in this repository, so it is reported (``artifacts/trivy-report.json``)
    and does not block. Triaged IDs never reach this function — Trivy dropped them via
    ``--ignorefile`` before writing the report.
    """
    offenders: list[str] = []
    for result in _objects(report.get("Results")):
        for vuln in _objects(result.get("Vulnerabilities")):
            fixed_version = vuln.get("FixedVersion")
            if not fixed_version:
                continue
            offenders.append(f"{vuln.get('PkgName')} {vuln.get('VulnerabilityID')} -> {fixed_version}")
    return offenders


def _run(argv: Sequence[str]) -> int:
    """Run a command from the repository root, echoing it for the CI log."""
    print(f"$ {' '.join(argv)}", flush=True)
    completed = subprocess.run(argv, cwd=_ROOT, check=False)  # noqa: S603  # argv built here, no shell
    return completed.returncode


def _must_run(argv: Sequence[str]) -> None:
    """Run a command and propagate its exit code."""
    code = _run(argv)
    if code != 0:
        raise SystemExit(code)


def require_triage_file() -> None:
    """The triage file is policy, not an optional convenience: its absence is an error."""
    if not _IGNORE_FILE.is_file():
        raise SystemExit(f"missing triage file: {display_path(_IGNORE_FILE)}")


def build_image() -> None:
    """Build the runtime target — the artefact under scan."""
    _must_run(["docker", "build", "--target", "runtime", "-t", _IMAGE_TAG, "."])


def save_image() -> None:
    """Export the image to a tarball so Trivy needs no Docker socket or registry access."""
    _must_run(["docker", "save", "-o", str(_IMAGE_TAR), _IMAGE_TAG])


def discard_image_tar() -> None:
    """Drop the multi-gigabyte tarball; it is transport for the scanner, not an artefact."""
    _IMAGE_TAR.unlink(missing_ok=True)


def scan_image() -> None:
    """Scan the image and leave the full HIGH/CRITICAL report in ``artifacts/``."""
    _must_run(trivy_scan_argv(repo_mount()))


def fail_on_fixable_findings() -> None:
    """Fail the build when a finding in the report has a fix we have not taken."""
    report = json.loads(_REPORT_PATH.read_text(encoding="utf-8"))
    offenders = fixable_findings(report)
    if not offenders:
        return
    listing = "\n".join(f"  {entry}" for entry in offenders)
    raise SystemExit(
        f"image scan failed: {len(offenders)} fixable HIGH/CRITICAL finding(s)\n{listing}\n"
        f"fix the dependency/base image, or triage the finding in {display_path(_IGNORE_FILE)} "
        f"with reason, ticket and review date"
    )


def write_sbom() -> None:
    """Generate the CycloneDX SBOM of the image."""
    _must_run(trivy_sbom_argv(repo_mount()))


def workflow_identity() -> str:
    """OIDC identity of the running workflow — what the signature must be verified against.

    Keyless cosign binds a signature to the workflow that produced it, not to a long-lived key:
    verification names the expected identity so a signature from a fork or another repository
    cannot pass as ours.
    """
    workflow_ref = os.environ.get("GITHUB_WORKFLOW_REF")
    if not workflow_ref:
        raise SystemExit("--sign requires GITHUB_WORKFLOW_REF (GitHub Actions OIDC identity)")
    return f"https://github.com/{workflow_ref}"


def sign_and_verify_sbom() -> None:
    """Sign the SBOM keyless, then verify it against the workflow identity (025)."""
    if shutil.which("cosign") is None:
        raise SystemExit("cosign is not on PATH: install it before --sign (CI uses the pinned sigstore action)")
    identity = workflow_identity()
    _must_run(["cosign", "sign-blob", "--yes", f"--bundle={_BUNDLE_PATH}", str(_SBOM_PATH)])
    _must_run(
        [
            "cosign",
            "verify-blob",
            f"--bundle={_BUNDLE_PATH}",
            f"--certificate-identity={identity}",
            f"--certificate-oidc-issuer={_GITHUB_OIDC_ISSUER}",
            str(_SBOM_PATH),
        ]
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """CLI: ``--no-build`` for a local re-scan, ``--sign`` for the CI provenance step."""
    parser = argparse.ArgumentParser(description="Image scan, SBOM and signature for the release artefact.")
    parser.add_argument(
        "--no-build",
        action="store_true",
        help=f"scan the existing {_IMAGE_TAG} image instead of rebuilding it",
    )
    parser.add_argument(
        "--sign",
        action="store_true",
        help="keyless-sign the SBOM with cosign and verify it against this workflow identity (CI only)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the artefact gates in order; non-zero on the first failure."""
    args = parse_args(argv)
    assert_digest_pinned(TRIVY_IMAGE)
    require_triage_file()
    _ARTIFACTS.mkdir(exist_ok=True)
    if not args.no_build:
        build_image()
    save_image()
    try:
        scan_image()
        fail_on_fixable_findings()
        write_sbom()
        if args.sign:
            sign_and_verify_sbom()
    finally:
        discard_image_tar()
    print("ci_supply_chain: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
