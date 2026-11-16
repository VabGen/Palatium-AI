#!/usr/bin/env python
r"""Pre-P1 gates: GFM fidelity of the deterministic renderer + HITL menu risk.

Run against real stored assistant documents — no LLM calls, no network. Export first
(the payload is PII: keep it outside the repo, e.g. ``%TEMP%``)::

    docker exec palatium-ai-postgres-1 psql -U postgres -d postgres -c \
      "\\copy (select payload::text from palatium_ai.dialog_turns \
      where role='assistant' and payload is not null) to '/tmp/assistant_turns.jsonl'"
    docker cp palatium-ai-postgres-1:/tmp/assistant_turns.jsonl %TEMP%\assistant_turns.jsonl

Two independent measurements:

1. ``structure_recall`` — for each GFM construct, does
   ``markdown_to_content_document`` preserve it? Exception counting is useless
   here: the parser degrades silently instead of raising, so a construct can be
   lost while the call "succeeds".
2. ``menu_shaped_rate`` by ``HitlInteractionPolicy`` — the real HITL risk when
   ``writer=worker`` makes lists far more likely (deterministic GFM render turns
   every ``- item`` line into ``ListBlock``).

Usage::

    uv run python scripts/measure_structure_fidelity.py
    uv run python scripts/measure_structure_fidelity.py --turns artifacts/assistant_turns.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from _diagnostics_common import formatter_task_input

from palatium_ai.application.agents.formatter.markdown_parser import markdown_to_content_document
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.hitl.interaction_policy import HitlInteractionPolicy

_DEFAULT_TURNS = Path(os.environ.get("TURNS_JSONL", "artifacts/assistant_turns.jsonl"))

#: GFM constructs the Formatter prompt may ask for, with an independent check that
#: the parsed document still carries the construct's information. Syntax follows the
#: parser's own contract (``markdown_parser``): callout marker on its own line,
#: definition pairs as ``- **Label**: value`` bullets, steps as ``N. **Title**: body``.
FIDELITY_CASES: tuple[tuple[str, str], ...] = (
    (
        "table",
        "| Параметр | Файл A | Файл B |\n|---|---|---|\n| Раздел 3 | нет | есть |\n| Дата | 12.01 | 14.01 |",
    ),
    ("nested_list_2", "- Первый\n  - Вложенный\n- Второй"),
    ("code_fence_in_list", "1. Проверить\n\n   ```python\n   print(1)\n   ```\n\n2. Готово"),
    ("callout", "> [!warning]\n> Важно\n> Проверьте дату."),
    ("callout_inline_title", "> [!warning] Важно\n> Проверьте дату."),
    ("key_value", "- **Адрес**: Минск\n- **Телефон**: 205-55-65"),
    ("key_value_no_bullet", "**Адрес**: Минск\n**Телефон**: 205-55-65"),
    ("heading_h2", "## Сравнение\n\nТекст."),
    ("steps", "1. **Первый**: сделать\n2. **Второй**: проверить"),
    ("inline_code_table", "| Выражение | Итог |\n|---|---|\n| `a|b` | x |"),
    ("plain_paragraph", "Просто абзац без структуры."),
    ("mojibake_cp1251", "ÐŸÑ€Ð¸Ð²ÐµÑ‚, ÑÐºÐ°Ð¶Ð¸Ñ‚Ðµ Ð´Ð°Ñ‚Ñƒ."),  # noqa: RUF001 — fixture is intentionally broken text
)


@dataclass(frozen=True, slots=True)
class FidelityRow:
    construct: str
    blocks: list[str]
    preserved: str


def _fidelity(markdown: str) -> list[str]:
    """Return the block types the deterministic parser produces."""
    document = markdown_to_content_document(markdown, formatter_task_input())
    return [block.type for block in document.blocks]


def _verdict(ok: bool) -> str:
    return "preserved" if ok else "degraded"


def _preserved(name: str, types: list[str], markdown: str) -> str:
    """Verdict per construct: ``preserved`` / ``degraded`` / ``unsupported``."""
    if name in {"table", "inline_code_table"}:
        return _verdict("table" in types)
    if name.startswith("callout"):
        return _verdict("callout" in types)
    if name.startswith("key_value"):
        return _verdict("kv" in types)
    if name == "heading_h2":
        return _verdict("heading" in types)
    if name == "nested_list_2":
        # ``ListBlock`` has no child items — nesting is unrepresentable by the
        # document model itself, so flattening is correct behaviour, and the prompt
        # must not ask for it. Not a parser defect (see plan §4).
        return "unsupported"
    if name == "code_fence_in_list":
        # A single contiguous step must not become two separate lists.
        return _verdict(types.count("list") == 1 and "code" in types)
    if name == "steps":
        return _verdict("steps" in types)
    if name == "plain_paragraph":
        return _verdict(types == ["paragraph"])
    if name == "mojibake_cp1251":
        # No detector in the parser: broken bytes render as valid text.
        return "undetected"
    return "degraded"


def measure_fidelity() -> list[FidelityRow]:
    rows: list[FidelityRow] = []
    for name, markdown in FIDELITY_CASES:
        types = _fidelity(markdown)
        rows.append(
            FidelityRow(
                construct=name,
                blocks=types,
                preserved=_preserved(name, types, markdown),
            )
        )
    return rows


def _load_documents(path: Path) -> tuple[list[ContentDocument], int]:
    """Parse a JSONL export of assistant payloads; return (documents, skipped lines)."""
    documents: list[ContentDocument] = []
    skipped = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                document = (payload or {}).get("document")
                if not isinstance(document, dict):
                    skipped += 1
                    continue
                documents.append(ContentDocument.model_validate(document))
            except json.JSONDecodeError, KeyError, ValueError:
                skipped += 1
    return documents, skipped


def measure_turns(path: Path) -> dict[str, object]:
    documents, skipped = _load_documents(path)

    block_counts: Counter[str] = Counter()
    with_list = 0
    menu_shaped = 0
    for document in documents:
        types = [block.type for block in document.blocks]
        block_counts.update(types)
        if "list" in types:
            with_list += 1
            plan = HitlInteractionPolicy.plan(
                document,
                requires_review=document.meta.requires_review,
                selected_strategy="reason_only",
                task_kind="knowledge_request",
                requires_user_choice=False,
                has_turn_attachments=False,
            )
            if plan.menu_shaped:
                menu_shaped += 1

    total = len(documents) or 1
    presence = {
        block_type: sum(1 for document in documents if any(block.type == block_type for block in document.blocks))
        for block_type in ("list", "table", "callout", "kv", "steps", "code")
    }
    return {
        "documents": len(documents),
        "skipped": skipped,
        "block_type_counts": dict(block_counts.most_common()),
        "documents_with_block": presence,
        "documents_with_list": with_list,
        "documents_menu_shaped": menu_shaped,
        "list_share": round(with_list / total, 4),
        "menu_shaped_share_of_all": round(menu_shaped / total, 4),
        "menu_shaped_share_of_lists": round(menu_shaped / with_list, 4) if with_list else 0.0,
        "avg_blocks": round(sum(block_counts.values()) / total, 2),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=Path, default=_DEFAULT_TURNS)
    args = parser.parse_args(argv)

    fidelity = measure_fidelity()
    print("## GFM fidelity (markdown_to_content_document)\n")
    print("| construct | blocks | verdict |")
    print("|---|---|---|")
    for row in fidelity:
        blocks = ", ".join(row.blocks) or "-"
        print(f"| {row.construct} | {blocks} | {row.preserved} |")
    degraded = sum(1 for row in fidelity if row.preserved != "preserved")
    print(f"\n{len(fidelity) - degraded}/{len(fidelity)} constructs survive the round trip\n")

    if not args.turns.exists():
        print(f"turns file not found: {args.turns} (skipping corpus stats)")
        return 0

    stats = measure_turns(args.turns)
    print("## Real documents\n")
    for key, value in stats.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
