#!/usr/bin/env python3
"""W10 remaining-gaps probe: Neo4j baseline + promote one-shot + attribution note."""

from __future__ import annotations

import json
import subprocess
import sys

from pathlib import Path
from typing import TypedDict

from neo4j import GraphDatabase

OUT = Path(__file__).resolve().parent / "artifacts" / "rerun"
NEO4J_URI = "bolt://127.0.0.1:7687"
NEO4J_AUTH = ("neo4j", "palatium-neo4j")
USER_ID = "w10-verifier"


class Neo4jSnapshot(TypedDict):
    facts: int
    rels: int
    kinds: list[dict[str, object]]
    sources: list[dict[str, object]]


def neo4j_snapshot() -> Neo4jSnapshot:
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    with driver.session() as session:
        facts_row = session.run("MATCH (n:MemoryFact) RETURN count(n) AS c").single()
        rels_row = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()
        if facts_row is None or rels_row is None:
            raise RuntimeError("neo4j count query returned no row")
        facts = int(facts_row["c"])
        rels = int(rels_row["c"])
        kinds = [
            {"kind": row["k"], "c": row["c"]}
            for row in session.run(
                "MATCH (n:MemoryFact) "
                "RETURN coalesce(n.kind, '?') AS k, count(*) AS c ORDER BY c DESC"
            )
        ]
        sources = [
            {"source_type": row["s"], "c": row["c"]}
            for row in session.run(
                "MATCH (n:MemoryFact) "
                "RETURN coalesce(n.source_type, '?') AS s, count(*) AS c ORDER BY c DESC"
            )
        ]
    driver.close()
    return {"facts": facts, "rels": rels, "kinds": kinds, "sources": sources}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    before = neo4j_snapshot()
    # Trusted local CLI only (audit harness); argv is a fixed allow-list.
    proc = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "palatium_ai.jobs.memory_promote",
            "--user-id",
            USER_ID,
            "--limit",
            "50",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[3]),
    )
    after = neo4j_snapshot()
    payload = {
        "before": before,
        "after": after,
        "delta_facts": after["facts"] - before["facts"],
        "delta_rels": after["rels"] - before["rels"],
        "promote_exit": proc.returncode,
        "promote_stdout": (proc.stdout or "")[-2000:],
        "promote_stderr": (proc.stderr or "")[-2000:],
        "contract": {
            "chat_hot_path": "extract → medium only (never Neo4j MERGE)",
            "trigger": "memory-consolidate / memory_promote job (compose profile memory-jobs)",
            "gate": "PromotionPolicy: access_frequency + importance + origin_ceiling",
            "who": "CronJob / compose loop / operator one-shot — not Intent/Formatter",
        },
    }
    (OUT / "promote_probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if proc.returncode == 0 else proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
