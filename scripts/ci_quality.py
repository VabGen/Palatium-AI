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
            "tests/unit/test_followup_memory.py",
            "tests/unit/test_continuity_policy.py",
            "tests/unit/test_critic_policy.py",
            "tests/unit/test_offline_benchmark.py",
            "tests/unit/test_core_wave3.py",
            "tests/unit/test_infrastructure_wave4.py",
            "tests/unit/test_rls_user_scope.py",
            "tests/unit/test_presentation_wave5.py",
            "tests/unit/test_harness.py",
            "tests/unit/test_checkpoint_migration.py",
            "tests/unit/test_memory_scoring.py",
            "tests/unit/test_memory_namespace_policy.py",
            "tests/unit/test_mcp_memory_actor_binding.py",
            "tests/unit/test_mcp_stub_schema_wave7.py",
            "tests/unit/test_researcher_mcp_output_redaction.py",
            "tests/unit/test_context_builder.py",
            "tests/unit/test_hitl_respond_facade.py",
            "tests/unit/test_memory_save_service.py",
            "tests/unit/test_memory_forget_service.py",
            "tests/unit/test_memory_consolidate_service.py",
            "tests/unit/test_memory_api.py",
            "tests/unit/test_hooks_deny_shell.py",
            "tests/unit/test_mcp_rbac_guard.py",
            "tests/unit/test_hitl_scenario_matrix.py",
            "tests/unit/test_wave9_security_fixes.py",
            "tests/unit/test_intent_classifier.py",
            "tests/unit/test_context_weaver.py",
            "tests/unit/test_critic_format_passthrough.py",
            "tests/unit/test_formatter_agent.py",
            "tests/unit/test_text_ingestor_agent.py",
            "tests/unit/test_text_ingestor_bridge.py",
            "tests/unit/test_document_ingest_service.py",
            "tests/unit/test_documents_ingest_api.py",
            "tests/unit/test_platform_knowledge_ingest.py",
            "tests/unit/test_knowledge_search.py",
            "tests/unit/test_platform_memory_mcp.py",
            "tests/unit/test_memory_fact_persistence.py",
            "tests/unit/test_memory_consolidation.py",
            "tests/unit/test_graph_web_mcp.py",
            "tests/unit/test_web_search_port.py",
            "tests/unit/test_retrieval_policy.py",
            "tests/unit/test_neo4j_graph_port.py",
            "tests/unit/test_graph_port_factory.py",
            "tests/unit/test_eval_runner_cassette.py",
            "tests/eval/test_agent_eval_assets.py",
            "tests/integration/test_graph_intent_guardrails.py",
            "tests/integration/test_document_ingest_e2e.py",
            "tests/integration/test_memory_hitl_e2e.py",
            "tests/integration/test_memory_consolidate_hitl_e2e.py",
            "tests/integration/test_knowledge_postgres_search.py",
            "tests/integration/test_neo4j_graph_query.py",
            "tests/integration/test_memory_postgres_search.py",
        ],
    )
    _run("SLA math gate", ["poetry", "run", "python", "scripts/run_sla_gates.py", "--check-math"])
    _run("agent evals baseline", ["poetry", "run", "python", "scripts/run_agent_evals.py"])
    # Live --load-health (incl. concurrency=1000) is ops/staging only — not PR CI.
    _assert_pyjwt_not_shadowed()
    print("ci_quality: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
