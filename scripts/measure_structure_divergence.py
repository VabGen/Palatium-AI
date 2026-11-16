"""Baseline ``structure_divergence`` + formatter cost on real turns from checkpoints.

Reads terminal checkpoints (both ``execution`` and ``formatted`` set, same
``task_id``), pairs the Researcher draft with the final ContentDocument, and
reports the Pre-P1 gate: shingle containment and block coverage separately.
Formatter node duration comes from checkpoint ``ts`` (terminal minus previous step
in the same thread), so the cost of the second generation is visible per bucket.

Requires the local compose Postgres (host port 5434). Read-only.
"""

from __future__ import annotations

import statistics

from collections import Counter, defaultdict

from _diagnostics_common import Turn, collect_turns, percentile


def _bucket(divergence: float) -> str:
    if divergence < 0.05:
        return "0.00-0.05 verbatim"
    if divergence < 0.2:
        return "0.05-0.20"
    if divergence < 0.5:
        return "0.20-0.50 partial"
    if divergence < 0.8:
        return "0.50-0.80 rewrite"
    return "0.80-1.00 full regen"


def _report(turns: list[Turn]) -> None:
    results = [turn.result for turn in turns]
    divergence = [turn.divergence for turn in turns]
    coverage = [turn.coverage for turn in turns]
    containment = [result.shingle_containment for result in results]

    print(f"terminal turns: {len(results)}")
    print(f"final blocks total: {sum(result.final_blocks for result in results)}")
    print()
    print("| metric | mean | p50 | p90 | p95 | max |")
    print("|---|---|---|---|---|---|")
    for name, values in (
        ("shingle_containment", containment),
        ("block_coverage", coverage),
        ("structure_divergence", divergence),
    ):
        print(
            f"| {name} | {statistics.mean(values):.3f} | {percentile(values, 0.5):.3f} | "
            f"{percentile(values, 0.9):.3f} | {percentile(values, 0.95):.3f} | {max(values):.3f} |"
        )

    latencies = [turn.formatter_seconds for turn in turns if turn.formatter_seconds is not None]
    if latencies:
        print()
        print(
            f"formatter node seconds (n={len(latencies)}): mean {statistics.mean(latencies):.1f} | "
            f"p50 {percentile(latencies, 0.5):.1f} | p90 {percentile(latencies, 0.9):.1f} | "
            f"max {max(latencies):.1f}"
        )

    print()
    for threshold in (0.2, 0.3, 0.5):
        share = sum(1 for value in divergence if value >= threshold) / len(divergence)
        print(f"turns with structure_divergence >= {threshold}: {share:.1%}")
    for threshold in (0.5, 0.7, 0.9):
        share = sum(1 for value in coverage if value >= threshold) / len(coverage)
        print(f"turns with block_coverage >= {threshold}: {share:.1%}")
    print(f"turns where every block is covered: {sum(result.block_coverage == 1.0 for result in results) / len(results):.1%}")
    print(f"uncovered blocks total: {sum(result.uncovered_blocks for result in results)}")

    grouped: dict[str, list[Turn]] = defaultdict(list)
    for turn in turns:
        grouped[_bucket(turn.divergence)].append(turn)
    print()
    print("| divergence bucket | turns | share | mean blocks | mean formatter s |")
    print("|---|---|---|---|---|")
    for name in ("0.00-0.05 verbatim", "0.05-0.20", "0.20-0.50 partial", "0.50-0.80 rewrite", "0.80-1.00 full regen"):
        bucket = grouped.get(name, [])
        if not bucket:
            continue
        seconds = [turn.formatter_seconds for turn in bucket if turn.formatter_seconds is not None]
        mean_seconds = f"{statistics.mean(seconds):.1f}" if seconds else "-"
        mean_blocks = statistics.mean(turn.result.final_blocks for turn in bucket)
        print(f"| {name} | {len(bucket)} | {len(bucket) / len(turns):.1%} | {mean_blocks:.1f} | {mean_seconds} |")

    print()
    print("kinds:", dict(Counter(turn.document.meta.kind for turn in turns).most_common()))
    print()
    print("worst 5 (highest divergence):")
    for turn in sorted(turns, key=lambda item: item.divergence, reverse=True)[:5]:
        print(
            f"  {turn.divergence:.2f} | cov {turn.coverage:.2f} | "
            f"blocks {turn.result.final_blocks} | worker {len(turn.summary)}c | "
            f"{turn.formatter_seconds or 0:.0f}s | {turn.document.meta.kind} | "
            f"{turn.task_id[:8]} | {turn.document.title!r}"
        )


def main() -> None:
    turns = collect_turns()
    if not turns:
        print("no terminal turns found")
        return
    _report(turns)


if __name__ == "__main__":
    main()
