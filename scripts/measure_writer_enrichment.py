r"""Pre-P1 follow-up #3 (2026-10-19): enrichment rate + the 4 independent recall cases.

1. ``elaboration_rate`` / ``thinning_rate`` — on every paired turn, how often the
   Formatter substantially grows or shrinks the worker draft. Decides whether
   ``writer=worker`` loses enrichment (needs a hybrid pass) or only padding.
2. Missing-token detail for the low-recall turns that do **not** lose headings,
   i.e. the parser bugs a ``##`` prompt contract will not fix.

Requires local compose Postgres (read-only). Prints ASCII-safe aggregates.
"""

from __future__ import annotations

import json

from collections import Counter
from dataclasses import asdict, dataclass

from _diagnostics_common import (
    ENRICHMENT_REPORT_PATH,
    RECALL_GATE,
    VERBATIM_REPORT_PATH,
    blocks_text,
    collect_turns,
    norm,
    parse_blocks,
    percentile,
    token_novelty,
    token_recall,
)

THINNING = 0.80
ELABORATION = 1.20

#: Substantive elaboration = the formatter added prose, not just structure/padding.
SUBSTANTIVE_WORKER_CHARS = 400
SUBSTANTIVE_NOVELTY = 0.25

#: Turns quoted verbatim in the JSON report for manual inspection.
EXAMPLE_TASK_PREFIXES = ("d23fd3c4", "f76d9969", "f2525afa", "ea22c1f3", "15a9b15f", "3b1c69e8")


@dataclass(frozen=True, slots=True)
class RatioRow:
    """Chars/novelty comparison of the worker draft against the final document."""

    task_id: str
    ratio: float
    worker_chars: int
    formatter_chars: int
    divergence: float
    novelty: float

    @property
    def substantive(self) -> bool:
        return self.worker_chars >= SUBSTANTIVE_WORKER_CHARS and self.novelty >= SUBSTANTIVE_NOVELTY


@dataclass(frozen=True, slots=True)
class ExampleRow:
    """A ratio row plus both texts, for the JSON artifact."""

    task_id: str
    ratio: float
    worker_chars: int
    formatter_chars: int
    divergence: float
    novelty: float
    worker: str
    formatter: str

    @classmethod
    def from_ratio(cls, row: RatioRow, worker: str, formatter: str) -> ExampleRow:
        return cls(
            task_id=row.task_id,
            ratio=row.ratio,
            worker_chars=row.worker_chars,
            formatter_chars=row.formatter_chars,
            divergence=row.divergence,
            novelty=row.novelty,
            worker=worker,
            formatter=formatter,
        )


def _measure_turn(turn_task_id: str, summary: str, formatter_text: str, divergence: float) -> RatioRow:
    worker_text = norm(summary)
    worker_chars = len(worker_text)
    formatter_chars = len(formatter_text)
    return RatioRow(
        task_id=turn_task_id,
        ratio=formatter_chars / max(1, worker_chars),
        worker_chars=worker_chars,
        formatter_chars=formatter_chars,
        divergence=divergence,
        novelty=token_novelty(worker_text, formatter_text),
    )


def measure_enrichment() -> None:
    turns = collect_turns()
    rows: list[RatioRow] = []
    examples: list[ExampleRow] = []
    for turn in turns:
        formatter_text = blocks_text(turn.document.blocks)
        row = _measure_turn(turn.task_id, turn.summary, formatter_text, turn.divergence)
        rows.append(row)
        examples.append(ExampleRow.from_ratio(row, norm(turn.summary), formatter_text))

    ratios = [row.ratio for row in rows]
    thinning = [row for row in rows if row.ratio < THINNING and row.divergence >= 0.05]
    elaboration = [row for row in rows if row.ratio > ELABORATION]
    near = [row for row in rows if THINNING <= row.ratio <= ELABORATION]
    substantive = [row for row in elaboration if row.substantive]
    padding = [row for row in elaboration if not row.substantive]
    total = len(rows) or 1

    print(f"paired turns: {len(rows)}")
    print(
        f"ratio formatter/worker: p10 {percentile(ratios, 0.1):.2f} | "
        f"p50 {percentile(ratios, 0.5):.2f} | p90 {percentile(ratios, 0.9):.2f} | "
        f"max {max(ratios):.2f}"
    )
    print()
    for label, bucket in (
        (f"thinning (ratio < {THINNING}, non-verbatim)", thinning),
        (f"near-equal ({THINNING}..{ELABORATION})", near),
        (f"elaboration (ratio > {ELABORATION})", elaboration),
    ):
        print(f"- {label}: {len(bucket)} turns = {len(bucket) / total:.1%}")
    print()

    print(
        f"elaboration split: substantive (worker>={SUBSTANTIVE_WORKER_CHARS} chars, "
        f"novelty>={SUBSTANTIVE_NOVELTY}) {len(substantive)} = {len(substantive) / total:.1%} | "
        f"padding/structural {len(padding)} = {len(padding) / total:.1%}"
    )
    print()

    print("elaboration turns (ratio, worker->formatter, novelty):")
    for row in sorted(elaboration, key=lambda item: -item.novelty):
        marker = "SUBSTANTIVE" if row.substantive else "padding"
        print(
            f"  {row.task_id[:8]} {marker:<11} ratio {row.ratio:.2f} | {row.worker_chars} -> "
            f"{row.formatter_chars} | novelty {row.novelty:.2f} | divergence {row.divergence:.2f}"
        )
    print()
    print("thinning turns (formatter shrank the draft):")
    for row in sorted(thinning, key=lambda item: item.task_id)[:12]:
        print(
            f"  {row.task_id[:8]} ratio {row.ratio:.2f} | worker {row.worker_chars} -> "
            f"formatter {row.formatter_chars} | divergence {row.divergence:.2f}"
        )

    _write_enrichment_report(
        ratios=ratios,
        rows=rows,
        thinning=thinning,
        near=near,
        elaboration=elaboration,
        substantive=substantive,
        examples=examples,
    )


def _write_enrichment_report(
    *,
    ratios: list[float],
    rows: list[RatioRow],
    thinning: list[RatioRow],
    near: list[RatioRow],
    elaboration: list[RatioRow],
    substantive: list[RatioRow],
    examples: list[ExampleRow],
) -> None:
    ENRICHMENT_REPORT_PATH.parent.mkdir(exist_ok=True)
    ENRICHMENT_REPORT_PATH.write_text(
        json.dumps(
            {
                "ratios": {
                    "p10": percentile(ratios, 0.1),
                    "p50": percentile(ratios, 0.5),
                    "p90": percentile(ratios, 0.9),
                    "max": max(ratios),
                },
                "counts": {
                    "turns": len(rows),
                    "thinning": len(thinning),
                    "near_equal": len(near),
                    "elaboration": len(elaboration),
                    "substantive_elaboration": len(substantive),
                },
                "elaboration": [asdict(row) for row in sorted(elaboration, key=lambda item: -item.novelty)],
                "examples": [
                    asdict(example)
                    for example in sorted(examples, key=lambda item: item.task_id)
                    if example.task_id.startswith(EXAMPLE_TASK_PREFIXES)
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def explain_independent_recall() -> None:
    """Dump low-recall turns whose loss cannot be blamed on a dropped heading."""
    report = json.loads(VERBATIM_REPORT_PATH.read_text(encoding="utf-8"))
    independent: list[tuple[str, float, int, str]] = []
    for row in report["verbatim"]:
        stored_blocks = parse_blocks(row["stored_blocks_json"])
        parsed_blocks = parse_blocks(row["parsed_blocks_json"])
        stored_types = Counter(block.type for block in stored_blocks)
        parsed_types = Counter(block.type for block in parsed_blocks)
        heading_loss = stored_types["heading"] - parsed_types["heading"]
        stored_text = blocks_text(stored_blocks)
        parsed_text = blocks_text(parsed_blocks)
        recall = token_recall(stored_text, parsed_text)
        if recall >= RECALL_GATE or heading_loss > 0:
            continue
        missing = Counter(stored_text.split()) - Counter(parsed_text.split())
        top = ", ".join(f"{token!r}x{count}" for token, count in missing.most_common(8))
        independent.append((str(row["task_id"]), recall, heading_loss, top))

    print()
    print(f"## low-recall turns independent of heading loss: {len(independent)}")
    for task_id, recall, heading_loss, top in independent:
        print(f"- {task_id[:8]} recall {recall:.3f} heading_loss {heading_loss}: {top}")


def main() -> None:
    measure_enrichment()
    explain_independent_recall()


if __name__ == "__main__":
    main()
