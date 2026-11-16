# tests/eval/test_memory_cmd0_measurability.py

"""CMD0: fixtures + metric stubs exist (no behavior change required beyond registry)."""

from __future__ import annotations

import json

from pathlib import Path

from palatium_ai.core.observability.metrics import agent_metrics

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "memory_cmd"


def test_cmd0_origin_trust_fixture_present() -> None:
    payload = json.loads((_FIXTURES / "origin_trust_schema.json").read_text(encoding="utf-8"))
    assert payload["adr"] == "0008"
    assert "extract" in payload["origins"]
    assert "inferred" in payload["trusts"]


def test_cmd0_prompt_tiers_fixture_marks_cmd2_gap() -> None:
    payload = json.loads((_FIXTURES / "prompt_tiers_expected.json").read_text(encoding="utf-8"))
    assert payload["wave"] == "CMD2"
    assert payload["status"] == "implemented_cmd2"
    assert [t["name"] for t in payload["tiers"]] == ["stable", "context", "volatile"]


def test_cmd0_metric_stubs_recordable() -> None:
    agent_metrics.record_memory_trust_upgrade(reason="verified_overlap")
    agent_metrics.record_memory_origin_ceiling(action="demoted")
    agent_metrics.record_prompt_cache_hint(tier="stable")
    agent_metrics.record_prompt_cache_tokens(cache_read_tokens=10, cache_write_tokens=2)
