# tests/eval/test_agent_inventory.py

"""W6 dead-code / graph inventory — every package has an explicit disposition."""

from __future__ import annotations

import ast

from pathlib import Path

from palatium_ai.application.agents.evals.agent_inventory import (
    AGENT_INVENTORY,
    AGENT_PACKAGE_NAMES,
    GRAPH_AGENT_FIELDS,
)
from palatium_ai.application.agents.evals.runner import AGENT_PACKAGES
from palatium_ai.application.orchestration.agent_registry import GraphAgents

_AGENTS_ROOT = Path(__file__).resolve().parents[2] / "src" / "palatium_ai" / "application" / "agents"
_REGISTRY = Path(__file__).resolve().parents[2] / "src" / "palatium_ai" / "application" / "orchestration" / "agent_registry.py"


def test_inventory_has_no_unknown_and_covers_packages() -> None:
    assert AGENT_INVENTORY
    for row in AGENT_INVENTORY:
        assert row.disposition in {"keep", "reserve", "delete"}
        assert row.notes.strip()
    package_agents = {row.agent.split(".", 1)[0] for row in AGENT_INVENTORY}
    assert set(AGENT_PACKAGE_NAMES) == package_agents


def test_every_eval_package_has_inventory_and_tasks() -> None:
    inventory_packages = {row.agent.split(".", 1)[0] for row in AGENT_INVENTORY if row.has_eval}
    assert set(AGENT_PACKAGES) <= inventory_packages
    for agent in AGENT_PACKAGES:
        assert (_AGENTS_ROOT / agent / "evals" / "tasks.json").is_file()
        assert (_AGENTS_ROOT / agent / "evals" / "grader.py").is_file()


def test_graph_agents_fields_match_inventory_graph_rows() -> None:
    field_names = {name for name in GraphAgents.__dataclass_fields__ if name.endswith("_agent")}
    assert field_names == GRAPH_AGENT_FIELDS
    graph_rows = [row for row in AGENT_INVENTORY if row.in_graph]
    assert len(graph_rows) == len(GRAPH_AGENT_FIELDS)


def test_off_graph_agents_marked_keep_with_reserved_note() -> None:
    off_graph = [row for row in AGENT_INVENTORY if not row.in_graph]
    assert {row.agent for row in off_graph} == {"memory_keeper", "text_ingestor"}
    for row in off_graph:
        assert row.disposition == "keep"
        assert row.has_eval is True
        assert row.review_trigger
        assert "ADR-0010" in row.review_trigger or "6 months" in row.review_trigger
        init_text = (_AGENTS_ROOT / row.agent / "__init__.py").read_text(encoding="utf-8")
        assert "reserved for future" in init_text
        assert "Review trigger" in init_text
        assert "ADR-0010" in init_text


def test_adr_0010_closure_record_exists() -> None:
    import re

    from datetime import date

    adr = Path(__file__).resolve().parents[2] / "docs" / "adr" / "0010-agents-audit-w1-w6-closure.md"
    text = adr.read_text(encoding="utf-8")
    assert "baseline-refresh" in text
    assert "fail-soft" in text
    assert "Next audit trigger" in text
    # Deadline must be a future calendar date (not a stale typo like 2026-05-10).
    match = re.search(
        r"не позже\s+\*?\*?(\d{4}-\d{2}-\d{2})\*?\*?",
        text,
    )
    assert match, "ADR-0010 next-audit deadline date missing"
    deadline = date.fromisoformat(match.group(1))
    assert deadline > date.today(), f"next-audit trigger {deadline} is not in the future"


def test_registry_imports_do_not_instantiate_orphans() -> None:
    """Static: agent_registry.py only binds GraphAgents fields — no stray Agent( calls."""
    tree = ast.parse(_REGISTRY.read_text(encoding="utf-8"))
    calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id.endswith("Agent")
    ]
    # Registry imports agents but constructs via GraphAgents fields in wiring, not here.
    assert calls == []
