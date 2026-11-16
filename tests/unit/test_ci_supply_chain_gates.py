"""Artefact supply-chain gates must be able to fail (025, 075, 082).

``scripts/ci_supply_chain.py`` stands between a build and a release artefact: it scans the
image that ships, emits the SBOM, and signs it. Three failure modes are silent, so they are
pinned here:

* the blocking rule drifting into "any severity finding" — unpatched Debian findings would make
  every PR red until someone deletes the gate (082);
* the blocking rule drifting into "no findings" — a report nobody reads while CVEs pile up;
* an unpinned scanner image — the tool that judges our supply chain is itself part of it.

Docker is not required: only the argv builders, the report filter and the policy guards run.
"""

from __future__ import annotations

import importlib.util
import json
import sys

from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "ci_supply_chain.py"

_FIXED = {"PkgName": "urllib3", "VulnerabilityID": "CVE-2026-97687", "FixedVersion": "2.8.0"}
_UNFIXED = {"PkgName": "libncursesw6", "VulnerabilityID": "CVE-2025-69720", "FixedVersion": ""}


def _load_module():
    """Import ``scripts/ci_supply_chain.py`` without making ``scripts`` a package."""
    spec = importlib.util.spec_from_file_location("ci_supply_chain_under_test", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ci_supply_chain_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _joined(argv: list[str]) -> str:
    """Argv as one searchable string — order-insensitive assertions stay readable."""
    return " ".join(argv)


def _report(*vulnerabilities: dict[str, Any]) -> dict[str, Any]:
    return {"Results": [{"Target": "Python", "Vulnerabilities": list(vulnerabilities)}]}


def test_scanner_image_is_digest_pinned() -> None:
    """A mutable tag would let the scanner change without a pull request in this repo."""
    module = _load_module()

    module.assert_digest_pinned(module.TRIVY_IMAGE)  # must not raise
    with pytest.raises(SystemExit):
        module.assert_digest_pinned("aquasec/trivy:latest")


def test_scan_is_a_single_json_pass_under_policy() -> None:
    """One scan feeds both the report and the gate; policy comes from files, not from luck."""
    module = _load_module()

    argv = module.trivy_scan_argv("/repo")
    joined = _joined(argv)

    assert argv.count("image") == 1, "a second pass would double the cost of the slowest gate"
    assert "--format json" in joined
    assert "artifacts/trivy-report.json" in joined
    assert "security/trivy-ignore.txt" in joined, "accepted risks must be reviewable in the repo"
    assert "--skip-dirs **/pip/_vendor/**" in joined, "pip's vendored copies are not distributions"
    assert "--timeout 15m" in joined, "Trivy's 5-minute default is shorter than a real image scan"
    assert "--severity CRITICAL,HIGH" in joined
    assert "--exit-code 0" in joined, "the gate is fixable_findings, not the scanner's severity filter"


def test_only_fixable_findings_block() -> None:
    """An upstream gap with no published fix is reported, never a reason to block a PR."""
    module = _load_module()

    assert module.fixable_findings(_report(_FIXED, _UNFIXED)) == ["urllib3 CVE-2026-97687 -> 2.8.0"]


@pytest.mark.parametrize(
    "report",
    (
        {},
        {"Results": []},
        {"Results": [{"Target": "debian", "Vulnerabilities": None}]},
        {"Results": [{"Target": "debian"}]},
    ),
)
def test_report_shapes_without_findings_are_not_offenders(report: dict[str, Any]) -> None:
    """Trivy omits empty sections; the gate must not turn that into a crash."""
    assert _load_module().fixable_findings(report) == []


def test_malformed_vulnerability_section_is_ignored() -> None:
    """A schema change in Trivy must not be read as 'all clear' with a traceback."""
    module = _load_module()

    assert module.fixable_findings({"Results": [{"Vulnerabilities": "nope"}]}) == []


def test_fixable_finding_fails_the_gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The blocking path: the operator gets the package, the CVE and where to triage."""
    module = _load_module()
    report_path = tmp_path / "trivy-report.json"
    report_path.write_text(json.dumps(_report(_FIXED)), encoding="utf-8")
    monkeypatch.setattr(module, "_REPORT_PATH", report_path)

    with pytest.raises(SystemExit) as excinfo:
        module.fail_on_fixable_findings()

    message = str(excinfo.value)
    assert "CVE-2026-97687" in message
    assert "security/trivy-ignore.txt" in message


def test_unfixable_findings_pass_the_gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The pass path: the very same report with only upstream gaps stays green."""
    module = _load_module()
    report_path = tmp_path / "trivy-report.json"
    report_path.write_text(json.dumps(_report(_UNFIXED)), encoding="utf-8")
    monkeypatch.setattr(module, "_REPORT_PATH", report_path)

    assert module.fail_on_fixable_findings() is None


def test_sbom_is_cyclonedx_in_the_artifacts_directory() -> None:
    """CycloneDX 1.6+ is the SBOM format this repo standardises on (025)."""
    module = _load_module()

    argv = _joined(module.trivy_sbom_argv("/repo"))

    assert "--format cyclonedx" in argv
    assert "artifacts/sbom.cdx.json" in argv
    assert "--input /scan/artifacts/palatium-ai-ci-scan.tar" in argv
    assert "--timeout 15m" in argv


def test_mount_paths_are_container_relative() -> None:
    """The scanner runs in a container: an absolute host path would silently scan nothing."""
    module = _load_module()

    mount = module.repo_mount()

    assert "\\" not in mount, "Docker needs forward slashes"
    assert module.container_path(module._SBOM_PATH) == "/scan/artifacts/sbom.cdx.json"


def test_missing_triage_file_is_an_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The triage file is policy, not an optional convenience."""
    module = _load_module()
    monkeypatch.setattr(module, "_IGNORE_FILE", tmp_path / "absent.txt")

    with pytest.raises(SystemExit):
        module.require_triage_file()


def test_committed_triage_file_exists() -> None:
    """The real invocation must find the file the blocking scan points at."""
    assert _load_module().require_triage_file() is None


def test_signature_identity_is_the_running_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keyless verification names the workflow: another repo's signature must not pass."""
    module = _load_module()
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", "acme/palatium-ai/.github/workflows/ci.yml@refs/heads/dev")

    assert module.workflow_identity() == ("https://github.com/acme/palatium-ai/.github/workflows/ci.yml@refs/heads/dev")


def test_signature_identity_requires_github_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Outside Actions there is no OIDC identity, so signing must refuse instead of guessing."""
    module = _load_module()
    monkeypatch.delenv("GITHUB_WORKFLOW_REF", raising=False)

    with pytest.raises(SystemExit):
        module.workflow_identity()
