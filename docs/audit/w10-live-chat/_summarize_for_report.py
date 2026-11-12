"""One-shot helper to print contested artifact details for W10 report."""

from __future__ import annotations

import json

from pathlib import Path

root = Path(__file__).resolve().parent / "artifacts"


def load(name: str):
    return json.loads((root / name).read_text(encoding="utf-8"))


h = load("turns/p1_howto.json")
print("p1_howto error:", h["raw_result"].get("error"))
print("confidence", h["raw_result"].get("confidence"), "status", h["raw_result"].get("status"))
print("hitl_cards", h["raw_result"].get("hitl_cards"))
print("steps_count", len(h["raw_result"]["output"]["blocks"][0].get("items") or []))

c = load("turns/p6_code.json")
for i, b in enumerate(c["raw_result"]["output"]["blocks"]):
    if b.get("type") == "code":
        t = b.get("text") or ""
        print(f"code[{i}] lang={b.get('language')!r} len={len(t)} head={t[:100]!r}")

list_turn = load("turns/p6_list.json")
for b in list_turn["raw_result"]["output"]["blocks"]:
    if b.get("type") == "list":
        items = b.get("items") or []
        print("list items", len(items), "sample", items[:2])

p2 = load("phase2.json")
print("\n===2a===")
for row in p2["2a"]["transcript"]:
    print("---", row["turn"], "pass=", row["pass"], "trace=", row["trace_id"])
    print("U:", row["user"])
    print("A:", row["assistant"][:400])

print("\n===2b===")
for row in p2["2b"]["transcript"]:
    print("---", row["turn"], "pass=", row["pass"], "trace=", row["trace_id"])
    print("U:", row["user"])
    print("A:", row["assistant"][:400])

print("\n===2c T1/T12===")
for row in p2["2c"]["transcript"]:
    if row["turn"] in {"2c_t1", "2c_t12"}:
        print("---", row["turn"], "pass=", row["pass"], "trace=", row["trace_id"])
        print("U:", row["user"])
        print("A:", row["assistant"][:500])

log = (root / "traces/p1_math_0cfa1a903646485db01ca08c048e6de1.log").read_text(encoding="utf-8", errors="replace")
print("\n===sample harness lines===")
shown = 0
for ln in log.splitlines():
    if any(k in ln for k in ("agent.handoff", "agent.turn.reasoning", "run_name': 'agent.run", "memory_keeper")):
        print(ln[:300])
        shown += 1
        if shown >= 12:
            break
