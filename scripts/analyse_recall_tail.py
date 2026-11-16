r"""Pre-P1 follow-up #2 (2026-10-19): token-recall tail and thinning/elaboration.

Two questions, both answerable from ``artifacts/verbatim_parse_report.json``
(no database, read-only):

1. Where do the low token-recall verbatim turns come from? If they are the same
   turns that lose worker headings, a ``##`` prompt contract fixes them; if they
   are independent parser bugs, the recall tail survives the prompt fix and the
   gate must be p50/p90 only with a p10/min warning.
2. For the ``both_acceptable`` tail turns, is the formatter *thinning* the worker
   answer (worker-as-writer is strictly richer) or *elaborating* it (worker-as-writer
   loses substance)? Decides whether P1 needs an enrichment pass or a hybrid.

Prints ASCII-safe aggregates; writes full detail to ``artifacts/`` (gitignored).
"""

from __future__ import annotations

import json
import re

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from _diagnostics_common import (
    RECALL_GATE,
    RECALL_TAIL_REPORT_PATH,
    VERBATIM_REPORT_PATH,
    blocks_text,
    parse_blocks,
    percentile,
    token_recall,
)

from palatium_ai.domain.content import ContentBlock

H2 = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
BOLD_LINE = re.compile(r"^\s*\*\*[^*\n]{2,80}\*\*\s*:?\s*$", re.MULTILINE)

# Manual direction verdicts from the 2026-10-19 review of the coverage==0 tail
# (turn-level, 18 turns). ``worse`` = formatter output is a degraded answer,
# ``acceptable`` = different but not a worse deliverable.
WORSE = {
    "e301d5fe",
    "87aaeb03",
    "4c0b06a2",
    "db8e9b61",
    "b385304b",
    "47625cae",
    "cde70b30",
    "cfefd20f",
    "c5afc66a",
    "d05a8bd5",
}


@dataclass(frozen=True, slots=True)
class RecallRow:
    """One verbatim report row, re-validated into typed blocks."""

    task_id: str
    recall: float
    heading_loss: int
    lost_types: dict[str, int]
    constructs: str
    worker: str
    stored_blocks: tuple[ContentBlock, ...]


def _heading_delta(stored: Iterable[ContentBlock], parsed: Iterable[ContentBlock]) -> int:
    stored_headings = sum(1 for block in stored if block.type == "heading")
    parsed_headings = sum(1 for block in parsed if block.type == "heading")
    return stored_headings - parsed_headings


def _lost_types(stored: Iterable[ContentBlock], parsed: Iterable[ContentBlock]) -> dict[str, int]:
    stored_types = Counter(block.type for block in stored)
    parsed_types = Counter(block.type for block in parsed)
    return {
        block_type: count - parsed_types.get(block_type, 0)
        for block_type, count in stored_types.items()
        if count > parsed_types.get(block_type, 0)
    }


def _recall_rows(verbatim: Sequence[dict[str, object]]) -> list[RecallRow]:
    rows: list[RecallRow] = []
    for row in verbatim:
        stored_blocks = parse_blocks(row["stored_blocks_json"])
        parsed_blocks = parse_blocks(row["parsed_blocks_json"])
        rows.append(
            RecallRow(
                task_id=str(row["task_id"]),
                recall=token_recall(blocks_text(stored_blocks), blocks_text(parsed_blocks)),
                heading_loss=_heading_delta(stored_blocks, parsed_blocks),
                lost_types=_lost_types(stored_blocks, parsed_blocks),
                constructs=str(row["constructs"]),
                worker=str(row["worker"]),
                stored_blocks=stored_blocks,
            )
        )
    return rows


def analyse_recall_tail(rows: Sequence[RecallRow]) -> list[str]:
    low = sorted((row for row in rows if row.recall < RECALL_GATE), key=lambda row: row.recall)
    lines = [
        f"verbatim turns: {len(rows)}",
        f"token_recall < {RECALL_GATE}: {len(low)} turns ({len(low) / max(1, len(rows)):.1%})",
        "",
        "id       recall heading_loss lost_types                          constructs",
    ]
    with_headings = 0
    for row in low:
        if row.heading_loss > 0:
            with_headings += 1
        lines.append(f"{row.task_id[:8]} {row.recall:.3f}  {row.heading_loss:>3}        {row.lost_types!s:<45} {row.constructs}")
    lines += [
        "",
        f"of those, turns losing headings: {with_headings}/{len(low)}",
        f"independent of heading loss:     {len(low) - with_headings}/{len(low)}",
    ]
    return lines


def analyse_tail_lengths(tail: Sequence[dict[str, object]]) -> list[str]:
    lines = [
        "id       verdict     worker_c formatter_c ratio delta  block_ids",
    ]
    grouped: dict[str, list[str]] = {}
    for row in tail:
        grouped.setdefault(str(row["worker"]), []).append(str(row["task_id"]))
    for worker_text, ids in grouped.items():
        primary = next(row for row in tail if str(row["task_id"]) == ids[0])
        formatter_text = blocks_text(parse_blocks(primary["stored_blocks_json"]))
        worker_len = len(worker_text)
        formatter_len = len(formatter_text)
        verdict = "worse" if any(identifier[:8] in WORSE for identifier in ids) else "acceptable"
        lines.append(
            f"{ids[0][:8]} {verdict:<11} {worker_len:>8} {formatter_len:>11} "
            f"{formatter_len / max(1, worker_len):.2f}  {formatter_len - worker_len:>+6}  {len(ids)}"
        )
    return lines


def _safe(line: str) -> str:
    return line.encode("ascii", "replace").decode("ascii")


def _percentiles(rows: Sequence[RecallRow]) -> dict[str, float]:
    recalls = sorted(row.recall for row in rows)
    return {
        "p50": percentile(recalls, 0.5),
        "p90": percentile(recalls, 0.9),
        "p10": percentile(recalls, 0.1),
        "min": min(recalls),
    }


def _write_report(
    *,
    percentiles: dict[str, float],
    rows: Sequence[RecallRow],
    tail: Sequence[dict[str, object]],
) -> None:
    RECALL_TAIL_REPORT_PATH.parent.mkdir(exist_ok=True)
    RECALL_TAIL_REPORT_PATH.write_text(
        json.dumps(
            {
                "percentiles": percentiles,
                "low_recall": [
                    {
                        "task_id": row.task_id,
                        "recall": row.recall,
                        "heading_loss": row.heading_loss,
                        "lost_types": row.lost_types,
                        "constructs": row.constructs,
                        "worker": row.worker,
                    }
                    for row in rows
                    if row.recall < RECALL_GATE
                ],
                "tail_lengths": [
                    {
                        "task_id": str(row["task_id"]),
                        "verdict": "worse" if str(row["task_id"])[:8] in WORSE else "acceptable",
                        "worker_chars": len(str(row["worker"])),
                        "formatter_chars": len(blocks_text(parse_blocks(row["stored_blocks_json"]))),
                    }
                    for row in tail
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"written {RECALL_TAIL_REPORT_PATH.as_posix()}")


def main() -> None:
    report = json.loads(VERBATIM_REPORT_PATH.read_text(encoding="utf-8"))
    rows = _recall_rows(report["verbatim"])
    tail = report["tail"]
    if not rows:
        print("verbatim turns: 0 (nothing to analyse)")
        return

    recall_lines = analyse_recall_tail(rows)
    length_lines = analyse_tail_lengths(tail)
    percentiles = _percentiles(rows)

    print("## token_recall distribution")
    for name, value in percentiles.items():
        print(f"- {name}: {value:.4f}")
    print()
    print("## low-recall turns")
    for line in recall_lines:
        print(_safe(line))
    print()
    print("## coverage==0 turns: worker vs formatter length (unique drafts)")
    for line in length_lines:
        print(_safe(line))

    acceptable = [row for row in tail if str(row["task_id"])[:8] not in WORSE]
    worse = [row for row in tail if str(row["task_id"])[:8] in WORSE]
    print()
    print(f"tail turns: {len(tail)} | acceptable {len(acceptable)} | worse {len(worse)}")

    _write_report(percentiles=percentiles, rows=rows, tail=tail)


if __name__ == "__main__":
    main()
