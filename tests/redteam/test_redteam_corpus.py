"""Nightly red-team corpus (S3): attacks must land on a refusal, not on a hope.

Every case is a deterministic system-under-test — no live LLM, so the job is about
*our* gates, not about a provider's mood tonight. Each attack class names the layer
that must catch it; `allowed` rows are negative controls: a suite that only ever
refuses would pass with every gate broken (075).

Marker `slow`: excluded from PR CI, run by `.github/workflows/redteam-nightly.yml`.
"""

from __future__ import annotations

import json

from pathlib import Path
from typing import Any

import pytest

from palatium_ai.core.security.prompt_injection import scan_prompt_injection
from palatium_ai.domain.mcp.tool_policy import is_tool_invocation_allowed
from palatium_ai.domain.policies.constitution import Constitution
from palatium_ai.domain.policies.untrusted_content import UntrustedContentPolicy

pytestmark = pytest.mark.slow

_CORPUS_PATH = Path(__file__).with_name("corpus.jsonl")


def _load_corpus() -> list[dict[str, Any]]:
    lines = _CORPUS_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


_CASES = _load_corpus()


def _case_id(case: dict[str, Any]) -> str:
    return str(case["id"])


def test_corpus_is_not_empty_and_has_controls() -> None:
    kinds = {case["kind"] for case in _CASES}
    expectations = {case["expect"] for case in _CASES}

    assert kinds == {"prompt_injection", "pii_exfiltration", "secret_echo", "tool_abuse"}
    # Negative controls, per class: otherwise "everything refused" would look green.
    assert "allow" in expectations
    assert "allowed" in expectations


@pytest.mark.parametrize("case", _CASES, ids=_case_id)
def test_attack_is_stopped_by_its_own_layer(case: dict[str, Any]) -> None:
    kind = case["kind"]

    if kind == "prompt_injection":
        report = scan_prompt_injection(str(case["payload"]))
        action = UntrustedContentPolicy.decide(report)
        allowed = action == "allow"
        assert allowed is (case["expect"] == "allow"), f"{case['id']}: action={action}"
        return

    if kind in {"pii_exfiltration", "secret_echo"}:
        violations = Constitution.check(
            draft=str(case["payload"]),
            sources=tuple(case.get("sources", ())),
        )
        principles = {violation.principle for violation in violations}
        if case["expect"] == "allowed":
            assert not principles, f"{case['id']}: unexpected {sorted(principles)}"
        else:
            assert case["expect"] in principles, f"{case['id']}: got {sorted(principles)}"
        return

    if kind == "tool_abuse":
        # The real invocation path: MCP goes through `mcp.call` + exact ref (070).
        allowed = is_tool_invocation_allowed(
            frozenset(case["allowed_tools"]),
            tool_name="mcp.call",
            server_name=str(case["server"]),
            mcp_tool_name=str(case["tool"]),
        )
        assert allowed is (case["expect"] == "allowed"), f"{case['id']}: allowed={allowed}"
        return

    pytest.fail(f"unknown attack class in corpus: {kind}")
