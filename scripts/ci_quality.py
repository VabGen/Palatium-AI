#!/usr/bin/env python
"""Cross-platform CI quality baseline (Week 5+)."""

from __future__ import annotations

import subprocess
import sys

from importlib import metadata
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _run(title: str, argv: list[str]) -> None:
    print(f"== {title} ==")
    completed = subprocess.run(argv, cwd=_ROOT, check=False)  # noqa: S603
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def _assert_pyjwt_not_shadowed() -> None:
    print("== conflict check: jwt vs PyJWT ==")
    names = {dist.metadata["Name"].lower() for dist in metadata.distributions()}
    if "jwt" in names and "pyjwt" in names:
        raise SystemExit(
            "Conflicting package 'jwt' is installed alongside PyJWT. "
            "Remove it (`poetry remove jwt` then `poetry sync`). Use PyJWT only."
        )
    from jwt import PyJWKClient  # noqa: F401

    print("PyJWT import OK")


def main() -> int:
    """Run ruff, mypy baseline, remediation unit tests, SLA math, PyJWT check."""
    _run("ruff", ["poetry", "run", "ruff", "check", "src/palatium_ai", "scripts", "tests/unit"])
    _run(
        "mypy --strict (src/palatium_ai)",
        [
            "poetry",
            "run",
            "mypy",
            "--strict",
            "src/palatium_ai",
        ],
    )
    _run(
        "unit: remediation + SLA",
        [
            "poetry",
            "run",
            "pytest",
            "-q",
            "tests/unit/test_api_auth_week0.py",
            "tests/unit/test_tool_policy_week1.py",
            "tests/unit/test_week2_sla.py",
            "tests/unit/test_week3_observability.py",
            "tests/unit/test_adversarial_drills.py",
            "tests/unit/test_session_ownership.py",
            "tests/unit/test_session_context_privacy.py",
            "tests/unit/test_environment_hardening.py",
            "tests/unit/test_sla_gates.py",
            "tests/unit/test_hitl_service.py",
            "tests/unit/test_hitl_escalation_policy.py",
            "tests/unit/test_hitl_shared_store.py",
            "tests/unit/test_hitl_phase0_adversarial.py",
            "tests/unit/test_hitl_interaction_policy.py",
            "tests/unit/test_choice_resume.py",
            "tests/unit/test_hitl_webhook_notifier.py",
            "tests/unit/test_hitl_email_slack_notifier.py",
            "tests/unit/test_hitl_idp_step_up.py",
            "tests/unit/test_audit_chain.py",
            "tests/unit/test_quality_hitl_revision.py",
            "tests/unit/test_hitl_quality_api.py",
            "tests/unit/test_workflow_policy.py",
            "tests/unit/test_social_routing.py",
            "tests/unit/test_continuity_policy.py",
            "tests/unit/test_critic_policy.py",
            "tests/unit/test_offline_benchmark.py",
        ],
    )
    _run("SLA math gate", ["poetry", "run", "python", "scripts/run_sla_gates.py", "--check-math"])
    # Live --load-health (incl. concurrency=1000) is ops/staging only — not PR CI.
    _assert_pyjwt_not_shadowed()
    print("ci_quality: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
