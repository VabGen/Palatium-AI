r"""Pre-P1 follow-up measurement (2026-10-19).

Answers three questions on real stored turns (read-only, no LLM):

1. ``verbatim_parse_success`` — among verbatim turns (worker text already ≈ final),
   how many survive ``markdown_to_content_document`` into the *same* document?
   This is the real share of turns where dropping the Formatter LLM call is safe;
   synthetic construct fidelity is not a substitute. Strict equality is reported
   next to two weaker verdicts (text identical / no information lost) so that
   "different segmentation" is not confused with "content lost".
2. Tail dump — every turn with ``block_coverage == 0``, so the "formatter worse /
   formatter rescued" direction can be judged.
3. Construct frequency in worker drafts (nested bullets, kv without bullet, …) and
   per-node timings for an offline deterministic TTFV baseline.

Writes PII reports to ``artifacts/`` (gitignored). Requires local compose Postgres.
"""

from __future__ import annotations

import json
import re

from collections import Counter
from dataclasses import dataclass, field

from _diagnostics_common import (
    VERBATIM_REPORT_PATH,
    Turn,
    block_parts,
    blocks_text,
    collect_turns,
    formatter_task_input,
    norm,
    percentile,
    token_recall,
)

from palatium_ai.application.agents.formatter.markdown_parser import markdown_to_content_document
from palatium_ai.domain.content import ContentBlock, ContentDocument

VERBATIM_DIVERGENCE = 0.05

_CALLOUT_TITLE = re.compile(r"^>\s*\[!\w+\]\s*\S", re.IGNORECASE | re.MULTILINE)
_KV_NO_BULLET = re.compile(r"^\*\*[^*\n]{1,60}\*\*\s*[:—–-]\s*\S", re.MULTILINE)
_NESTED_BULLET = re.compile(r"^\s{2,}[-*+]\s+\S", re.MULTILINE)
_FENCE_IN_LIST = re.compile(r"^\s{2,}```", re.MULTILINE)


@dataclass(slots=True)
class ParseOutcome:
    """How one worker draft survives the deterministic renderer."""

    exact: bool
    types_equal: bool
    text_equal: bool
    text_preserved: bool
    info_preserved: bool
    token_recall: float
    parsed_blocks: int
    stored_blocks: int
    failure: str = field(default="")


def _signature(block: ContentBlock) -> tuple[str, tuple[str, ...]]:
    return (block.type, block_parts(block))


def _outcome(parsed: ContentDocument, stored: ContentDocument) -> ParseOutcome:
    parsed_sig = [_signature(block) for block in parsed.blocks]
    stored_sig = [_signature(block) for block in stored.blocks]
    parsed_text = blocks_text(parsed.blocks)
    stored_text = blocks_text(stored.blocks)
    types_equal = [block_type for block_type, _ in parsed_sig] == [block_type for block_type, _ in stored_sig]
    failure = ""
    if parsed_sig != stored_sig:
        if not parsed_sig:
            failure = "parsed_empty"
        elif not types_equal:
            failure = "block_type_mismatch"
        else:
            failure = "text_mismatch"
    return ParseOutcome(
        exact=parsed_sig == stored_sig,
        types_equal=types_equal,
        text_equal=[parts for _, parts in parsed_sig] == [parts for _, parts in stored_sig],
        text_preserved=parsed_text == stored_text,
        info_preserved=all(norm(" ".join(parts)) in parsed_text for _, parts in stored_sig if any(parts)),
        token_recall=token_recall(stored_text, parsed_text),
        parsed_blocks=len(parsed.blocks),
        stored_blocks=len(stored.blocks),
        failure=failure,
    )


def _constructs(text: str) -> list[str]:
    found = []
    if _CALLOUT_TITLE.search(text):
        found.append("callout_with_title")
    if _KV_NO_BULLET.search(text):
        found.append("kv_no_bullet")
    if _NESTED_BULLET.search(text):
        found.append("nested_bullet")
    if _FENCE_IN_LIST.search(text):
        found.append("fence_in_list")
    return found


def _print_parse_verdicts(rows: list[tuple[Turn, ContentDocument, ParseOutcome]]) -> None:
    total = len(rows) or 1
    exact = sum(1 for _, _, outcome in rows if outcome.exact)
    types_ok = sum(1 for _, _, outcome in rows if outcome.types_equal)
    text_ok = sum(1 for _, _, outcome in rows if outcome.text_equal)
    preserved = sum(1 for _, _, outcome in rows if outcome.text_preserved)
    info = sum(1 for _, _, outcome in rows if outcome.info_preserved)
    failures = Counter(outcome.failure for _, _, outcome in rows if outcome.failure)

    print("## verbatim_parse_success")
    print(f"- exact (types + texts):     {exact}/{total} = {exact / total:.1%}")
    print(f"- type sequence equal:       {types_ok}/{total} = {types_ok / total:.1%}")
    print(f"- texts equal per block:     {text_ok}/{total} = {text_ok / total:.1%}")
    print(f"- concatenated text equal:   {preserved}/{total} = {preserved / total:.1%}")
    print(f"- no information lost:       {info}/{total} = {info / total:.1%}")
    recalls = sorted(outcome.token_recall for _, _, outcome in rows)
    print(
        f"- token recall: mean {sum(recalls) / total:.4f} | p10 {recalls[max(0, total // 10)]:.4f} | "
        f"min {min(recalls):.4f} | turns >= 0.99: {sum(1 for recall in recalls if recall >= 0.99)}/{total}"
    )
    print(f"- failures: {dict(failures)}")
    print(
        f"- blocks: parsed {sum(outcome.parsed_blocks for _, _, outcome in rows)} "
        f"vs stored {sum(outcome.stored_blocks for _, _, outcome in rows)}"
    )


def _print_block_delta(rows: list[tuple[Turn, ContentDocument, ParseOutcome]]) -> None:
    losses: Counter[str] = Counter()
    gains: Counter[str] = Counter()
    for turn, parsed, outcome in rows:
        if outcome.exact:
            continue
        stored_types = Counter(block.type for block in turn.document.blocks)
        parsed_types = Counter(block.type for block in parsed.blocks)
        for block_type, count in stored_types.items():
            if parsed_types.get(block_type, 0) < count:
                losses[block_type] += count - parsed_types.get(block_type, 0)
        for block_type, count in parsed_types.items():
            if stored_types.get(block_type, 0) < count:
                gains[block_type] += count - stored_types.get(block_type, 0)
    print()
    print("## block types lost / gained on failing turns")
    print(f"- lost:   {dict(losses.most_common())}")
    print(f"- gained: {dict(gains.most_common())}")
    print()


def _print_report(
    rows: list[tuple[Turn, ContentDocument, ParseOutcome]],
    turns: list[Turn],
) -> None:
    print(f"turns: {len(turns)} | verbatim (divergence < {VERBATIM_DIVERGENCE}): {len(rows)}")
    print()
    _print_parse_verdicts(rows)
    _print_block_delta(rows)

    construct_turns: Counter[str] = Counter()
    for turn in turns:
        construct_turns.update(_constructs(turn.summary))
    print(f"## constructs in worker drafts (n={len(turns)} turns)")
    for name, count in construct_turns.most_common():
        print(f"- {name}: {count} turns = {count / len(turns):.1%}")

    tail = [turn for turn in turns if turn.coverage == 0.0]
    print()
    print(f"## tail: coverage == 0 -> {len(tail)} turns")

    researcher = [turn.researcher_seconds for turn in turns if turn.researcher_seconds is not None]
    formatter = [turn.formatter_seconds for turn in turns if turn.formatter_seconds is not None]
    if researcher:
        print()
        print(
            f"researcher node seconds (n={len(researcher)}): p50 {percentile(researcher, 0.5):.1f} | "
            f"p90 {percentile(researcher, 0.9):.1f} | max {max(researcher):.1f}"
        )
    if formatter:
        print(
            f"formatter node seconds (n={len(formatter)}): p50 {percentile(formatter, 0.5):.1f} | "
            f"p90 {percentile(formatter, 0.9):.1f} | max {max(formatter):.1f}"
        )
    _print_timing_floor(turns)


def _print_timing_floor(turns: list[Turn]) -> None:
    """Offline estimate of what removing the formatter LLM call would save."""
    # Local bindings, not attribute reads in a comprehension: narrowing on
    # ``turn.researcher_seconds is not None`` does not survive into the element
    # expression, so the arithmetic would stay ``float | None`` for a checker.
    shares: list[float] = []
    saved: list[float] = []
    for turn in turns:
        researcher_seconds = turn.researcher_seconds
        formatter_seconds = turn.formatter_seconds
        if researcher_seconds is None or formatter_seconds is None:
            continue
        saved.append(formatter_seconds)
        shares.append(formatter_seconds / (researcher_seconds + formatter_seconds))
    if not saved:
        return
    print()
    print(f"offline deterministic-floor estimate (n={len(saved)} turns with both timings):")
    print(
        f"- removable formatter time: p50 {percentile(saved, 0.5):.1f}s | "
        f"p90 {percentile(saved, 0.9):.1f}s | total {sum(saved):.0f}s"
    )
    print(f"- formatter share of researcher+formatter: p50 {percentile(shares, 0.5):.1%} | p90 {percentile(shares, 0.9):.1%}")


def main() -> None:
    turns = collect_turns()
    if not turns:
        print("no paired turns found")
        return
    VERBATIM_REPORT_PATH.parent.mkdir(exist_ok=True)
    verbatim = [turn for turn in turns if turn.divergence < VERBATIM_DIVERGENCE]

    rows: list[tuple[Turn, ContentDocument, ParseOutcome]] = []
    for turn in verbatim:
        parsed = markdown_to_content_document(turn.summary, formatter_task_input())
        rows.append((turn, parsed, _outcome(parsed, turn.document)))

    _print_report(rows, turns)

    report = {
        "verbatim": [
            {
                "task_id": turn.task_id,
                "divergence": turn.divergence,
                "coverage": turn.coverage,
                "exact": outcome.exact,
                "info_preserved": outcome.info_preserved,
                "failure": outcome.failure,
                "parsed_blocks": outcome.parsed_blocks,
                "stored_blocks": outcome.stored_blocks,
                "constructs": _constructs(turn.summary),
                "worker_chars": len(turn.summary),
                "worker": turn.summary,
                "stored_blocks_json": [block.model_dump(mode="json") for block in turn.document.blocks],
                "parsed_blocks_json": [block.model_dump(mode="json") for block in parsed.blocks],
            }
            for turn, parsed, outcome in rows
        ],
        "tail": [
            {
                "task_id": turn.task_id,
                "divergence": turn.divergence,
                "coverage": turn.coverage,
                "worker_chars": len(turn.summary),
                "worker": turn.summary,
                "stored_title": turn.document.title,
                "stored_blocks_json": [block.model_dump(mode="json") for block in turn.document.blocks],
            }
            for turn in turns
            if turn.coverage == 0.0
        ],
    }
    VERBATIM_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written {VERBATIM_REPORT_PATH.as_posix()}")


if __name__ == "__main__":
    main()
