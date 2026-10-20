r"""Pre-P1 follow-up #4 (2026-10-19): callout baseline on the paired-turn population.

The 20.1 % callout share was measured over 646 stored documents, which mixes
turns and shape families. The post-P1 gate compares worker-owned turns with
today's formatter output on the *same* turns, so the baseline must be measured
on the paired population (``formatter.task_id == researcher.task_id``).

Prints the share of turns whose final document contains at least one callout,
plus the block-type distribution, so ``callout_presence_rate`` has a comparable
pre-P1 number.
"""

from __future__ import annotations

from collections import Counter

from _diagnostics_common import collect_turns

from palatium_ai.domain.content import CalloutBlock

CALL_OUT = "callout"


def main() -> None:
    turns = collect_turns()
    total = len(turns) or 1
    with_callout = 0
    types: Counter[str] = Counter()
    tones: Counter[str] = Counter()
    per_turn_types: Counter[str] = Counter()

    for turn in turns:
        present = False
        for block in turn.document.blocks:
            types[block.type] += 1
            if isinstance(block, CalloutBlock):
                present = True
                tones[block.tone] += 1
        if present:
            with_callout += 1
        for block_type in {block.type for block in turn.document.blocks}:
            per_turn_types[block_type] += 1

    print(f"paired turns: {len(turns)}")
    print(f"callout_presence_rate (>=1 callout per turn): {with_callout}/{total} = {with_callout / total:.1%}")
    print(f"callout tones: {dict(tones.most_common())}")
    print()
    print("block type distribution (all blocks):")
    block_total = sum(types.values()) or 1
    for block_type, count in types.most_common():
        print(f"- {block_type}: {count} ({count / block_total:.1%} of blocks)")
    print()
    print("turns containing at least one block of type:")
    for block_type, count in per_turn_types.most_common():
        print(f"- {block_type}: {count} turns = {count / total:.1%}")


if __name__ == "__main__":
    main()
