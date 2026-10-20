"""Explain verbatim-parse failures: heading loss vs over-eager block promotion."""

from __future__ import annotations

import json
import re

from collections import Counter
from pathlib import Path

H2 = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
BOLD_LINE = re.compile(r"^\s*\*\*[^*\n]{2,80}\*\*\s*:?\s*$", re.MULTILINE)

report = json.loads(Path("artifacts/verbatim_parse_report.json").read_text(encoding="utf-8"))
rows = report["verbatim"]

stats: Counter[str] = Counter()
examples: list[str] = []
for row in rows:
    if row["exact"]:
        continue
    stored = row["stored_blocks_json"]
    parsed = row["parsed_blocks_json"]
    worker = row["worker"]
    stored_types = Counter(b["type"] for b in stored)
    parsed_types = Counter(b["type"] for b in parsed)

    md_headings = len(H2.findall(worker))
    bold_headings = len(BOLD_LINE.findall(worker))
    heading_loss = stored_types["heading"] - parsed_types["heading"]

    if heading_loss > 0:
        stats["heading_loss_turns"] += 1
        stats["heading_loss_blocks"] += heading_loss
        if md_headings == 0 and bold_headings > 0:
            stats["heading_loss_from_bold_pseudoheadings"] += 1
    if parsed_types["kv"] > stored_types["kv"]:
        stats["kv_promoted_turns"] += 1
    if parsed_types["steps"] > stored_types["steps"]:
        stats["steps_promoted_turns"] += 1
    if parsed_types["list"] < stored_types["list"]:
        stats["list_merged_turns"] += 1

    examples.append(
        f"{row['task_id'][:8]} div={row['divergence']:.2f} "
        f"md_headings={md_headings} bold_lines={bold_headings} "
        f"headings {stored_types['heading']}->{parsed_types['heading']} "
        f"kv {stored_types['kv']}->{parsed_types['kv']} "
        f"list {stored_types['list']}->{parsed_types['list']} "
        f"info_preserved={row['info_preserved']}"
    )

print(f"failing verbatim turns: {len(examples)}")
print("\ncounters:", dict(stats))
print()
for line in examples:
    print(" ", line)
