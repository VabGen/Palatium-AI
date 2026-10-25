#!/usr/bin/env python
r"""W5 — backtest the deterministic ``ContentDocument`` lint against a stored corpus.

Read-only: no LLM, no network, no database writes. The corpus is the assistant
payload export the structure-fidelity script already uses (the payload holds PII, so
it stays outside the repo — ``artifacts/`` is gitignored)::

    docker exec palatium-ai-postgres-1 psql -U postgres -d postgres -c \
      "\\copy (select payload::text from palatium_ai.dialog_turns \
      where role='assistant' and payload is not null) to '/tmp/assistant_turns.jsonl'"
    docker cp palatium-ai-postgres-1:/tmp/assistant_turns.jsonl %TEMP%\assistant_turns.jsonl

    uv run python scripts/backtest_lint.py --turns %TEMP%\assistant_turns.jsonl

Why false positives are measured only on the curated golden set
---------------------------------------------------------------
The production corpus carries no labels: a rule firing on a real answer says nothing
about whether that answer was correct, so ``hits / documents`` there is a *share*, not
a false-positive rate. ``tests/fixtures/lint/legit_answers.jsonl`` is the labelled
side of the measurement — documents a human has read and declared legitimate — and its
findings are genuine false positives (plan W5, 086: the curated number is a gate, the
corpus share is a report).

A rule whose share exceeds ``--threshold`` (5 % by default) *and* does not correlate
with the judge is a candidate for ``warning`` severity instead of ``error``. The judge
correlation is a human step by design: the corpus has no judge scores, and inventing the
join would turn "не коррелирует с судьёй" into an assertion nobody verified (086).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.content.lint import ContentLint
from palatium_ai.domain.content.lint.rules import RULES

_DEFAULT_TURNS = Path(os.environ.get("TURNS_JSONL", "artifacts/assistant_turns.jsonl"))
_DEFAULT_GOLDEN = Path("tests/fixtures/lint/legit_answers.jsonl")
_DEFAULT_REPORT = Path("artifacts/lint_backtest.json")

#: A rule flagging more than this share of real answers needs a second look (plan W5).
HIGH_FINDING_SHARE = 0.05


@dataclass(frozen=True, slots=True)
class Corpus:
    """Validated documents of one JSONL export plus the lines that did not parse."""

    documents: tuple[ContentDocument, ...]
    skipped: int


@dataclass(frozen=True, slots=True)
class RuleSummary:
    """One rule over the whole corpus; present even when it never fired."""

    rule_id: str
    severity: str
    findings: int
    documents_hit: int
    #: ``meta.kind`` → documents hit. The intent axis ``response_shape`` is not part of
    #: the persisted payload, so it cannot be a breakdown dimension of this report.
    by_kind: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class Backtest:
    """Corpus-wide result, rules in the engine's fixed order."""

    documents: int
    skipped: int
    rules: tuple[RuleSummary, ...]

    def share(self, rule_id: str) -> float:
        """Share of corpus documents hit by one rule (``0.0`` for an unknown id)."""
        if not self.documents:
            return 0.0
        hit = next((rule.documents_hit for rule in self.rules if rule.rule_id == rule_id), 0)
        return hit / self.documents


@dataclass(frozen=True, slots=True)
class GoldenResult:
    """False-positive measurement on the curated (labelled) set."""

    documents: int
    skipped: int
    findings: int
    documents_hit: int
    by_rule: Mapping[str, int]

    @property
    def false_positive_rate(self) -> float:
        """Share of labelled-legitimate documents the lint flagged at all."""
        return self.documents_hit / self.documents if self.documents else 0.0


def load_corpus(path: Path) -> Corpus:
    """Parse a JSONL export of assistant payloads into documents.

    Lines that are not ``{"document": {...}}`` (or fail validation) are counted, never
    silently dropped: a loader that hides half the corpus would understate every share.
    """
    documents: list[ContentDocument] = []
    skipped = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
                document = (payload or {}).get("document")
                if not isinstance(document, dict):
                    skipped += 1
                    continue
                documents.append(ContentDocument.model_validate(document))
            except json.JSONDecodeError, KeyError, ValueError:
                skipped += 1
    return Corpus(documents=tuple(documents), skipped=skipped)


def run_backtest(corpus: Corpus) -> Backtest:
    """Run the closed rule set once over every document; aggregate per rule."""
    findings: Counter[str] = Counter()
    hit_documents: Counter[str] = Counter()
    by_kind: dict[str, Counter[str]] = defaultdict(Counter)
    for document in corpus.documents:
        report = ContentLint.run(document)
        hit_rules = {finding.rule_id for finding in report.findings}
        findings.update(finding.rule_id for finding in report.findings)
        hit_documents.update(hit_rules)
        for rule_id in hit_rules:
            by_kind[rule_id][document.meta.kind] += 1
    summaries = tuple(
        RuleSummary(
            rule_id=rule.rule_id,
            severity=rule.severity,
            findings=findings.get(rule.rule_id, 0),
            documents_hit=hit_documents.get(rule.rule_id, 0),
            by_kind=dict(by_kind.get(rule.rule_id, {})),
        )
        for rule in RULES
    )
    return Backtest(documents=len(corpus.documents), skipped=corpus.skipped, rules=summaries)


def measure_golden(corpus: Corpus) -> GoldenResult:
    """Count findings on documents a human declared legitimate — those are FP."""
    findings = 0
    by_rule: Counter[str] = Counter()
    documents_hit = 0
    for document in corpus.documents:
        report = ContentLint.run(document)
        if not report.findings:
            continue
        documents_hit += 1
        findings += len(report.findings)
        by_rule.update({finding.rule_id for finding in report.findings})
    return GoldenResult(
        documents=len(corpus.documents),
        skipped=corpus.skipped,
        findings=findings,
        documents_hit=documents_hit,
        by_rule=dict(by_rule),
    )


def high_share_rules(result: Backtest, threshold: float = HIGH_FINDING_SHARE) -> tuple[RuleSummary, ...]:
    """Rules flagged on more than ``threshold`` of the corpus (judge check is manual)."""
    if not result.documents:
        return ()
    return tuple(rule for rule in result.rules if rule.documents_hit / result.documents > threshold)


def render_markdown(result: Backtest, golden: GoldenResult, threshold: float = HIGH_FINDING_SHARE) -> str:
    """Human-readable report: per-rule share, FP on the golden set, review candidates."""
    lines = [
        "## Lint backtest (corpus)",
        "",
        f"- documents: {result.documents} (skipped lines: {result.skipped})",
        "",
        "| rule | severity | findings | documents hit | share | by kind |",
        "|---|---|---|---|---|---|",
    ]
    for rule in result.rules:
        share = rule.documents_hit / result.documents if result.documents else 0.0
        kinds = ", ".join(f"{kind}={count}" for kind, count in sorted(rule.by_kind.items())) or "-"
        lines.append(
            f"| `{rule.rule_id}` | {rule.severity} | {rule.findings} | {rule.documents_hit} | {share:.1%} | {kinds} |",
        )

    lines += [
        "",
        "## False positives (curated golden set)",
        "",
        f"- documents: {golden.documents} (skipped lines: {golden.skipped})",
        f"- documents with any finding: {golden.documents_hit} ({golden.false_positive_rate:.1%})",
        f"- findings: {golden.findings}",
    ]
    if golden.by_rule:
        for rule_id, count in sorted(golden.by_rule.items()):
            lines.append(f"- `{rule_id}`: {count} false-positive document(s)")

    candidates = high_share_rules(result, threshold)
    lines += ["", f"## Review candidates (share > {threshold:.0%})", ""]
    if not candidates:
        lines.append("none")
    else:
        for rule in candidates:
            share = rule.documents_hit / result.documents
            lines.append(
                f"- `{rule.rule_id}`: {share:.1%} of answers — compare with `palatium_judge_score` "
                f"before switching it to `warning` (manual step, no automated correlation)",
            )
    return "\n".join(lines)


def to_json(result: Backtest, golden: GoldenResult, threshold: float = HIGH_FINDING_SHARE) -> dict[str, object]:
    """Machine-readable twin of :func:`render_markdown` (no prose from documents)."""
    return {
        "documents": result.documents,
        "skipped": result.skipped,
        "threshold": threshold,
        "rules": [
            {
                "rule_id": rule.rule_id,
                "severity": rule.severity,
                "findings": rule.findings,
                "documents_hit": rule.documents_hit,
                "share": round(rule.documents_hit / result.documents, 4) if result.documents else 0.0,
                "by_kind": dict(rule.by_kind),
            }
            for rule in result.rules
        ],
        "golden": {
            "documents": golden.documents,
            "skipped": golden.skipped,
            "findings": golden.findings,
            "documents_hit": golden.documents_hit,
            "false_positive_rate": round(golden.false_positive_rate, 4),
            "by_rule": dict(golden.by_rule),
        },
        "review_candidates": [rule.rule_id for rule in high_share_rules(result, threshold)],
    }


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--turns", type=Path, default=_DEFAULT_TURNS, help="JSONL export of assistant payloads")
    parser.add_argument("--golden", type=Path, default=_DEFAULT_GOLDEN, help="curated legitimate documents")
    parser.add_argument("--json", type=Path, default=_DEFAULT_REPORT, help="report path (gitignored)")
    parser.add_argument("--threshold", type=float, default=HIGH_FINDING_SHARE, help="share that needs a review")
    args = parser.parse_args(argv)

    if not args.turns.exists():
        print(f"turns file not found: {args.turns} (export the corpus first, see the module docstring)")
        return 0

    result = run_backtest(load_corpus(args.turns))
    golden = measure_golden(load_corpus(args.golden)) if args.golden.exists() else GoldenResult(0, 0, 0, 0, {})
    if not args.golden.exists():
        print(f"golden set not found: {args.golden} (false-positive rate left unmeasured)")

    print(render_markdown(result, golden, args.threshold))

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(to_json(result, golden, args.threshold), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nwritten {args.json.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
