"""W5: the lint backtest must measure, not decorate (075, 086, 050).

Three things are pinned here:

* the curated golden set is large enough to be a measurement and stays clean — a
  finding on a document a human declared legitimate *is* a false positive;
* the aggregation cannot hide a rule: every rule of the closed set appears in the
  report even when it never fired, and a share is computed over all documents;
* the ``> 5 %`` review trigger is strictly greater, so the boundary case (exactly 5 %)
  does not silently promote a rule to the review list.
"""

from __future__ import annotations

import importlib.util
import json
import sys

from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import pytest

from palatium_ai.domain.content import (
    ContentBlock,
    ContentDocument,
    DocumentKind,
    DocumentMeta,
    ListBlock,
    ListItem,
    ParagraphBlock,
)
from palatium_ai.domain.content.lint import ContentLint

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "backtest_lint.py"
_GOLDEN_PATH = _REPO_ROOT / "tests" / "fixtures" / "lint" / "legit_answers.jsonl"


def _load_module() -> ModuleType:
    """Import ``scripts/backtest_lint.py`` without making ``scripts`` a package."""
    spec = importlib.util.spec_from_file_location("backtest_lint_under_test", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["backtest_lint_under_test"] = module
    spec.loader.exec_module(module)
    return module


#: Loaded once at collection so the parametrised FP check covers *every* fixture line:
#: a hard-coded count would silently exempt the case someone added next.
_GOLDEN = _load_module().load_corpus(_GOLDEN_PATH).documents


def _doc(*blocks: ContentBlock, kind: DocumentKind = "report") -> ContentDocument:
    return ContentDocument(
        locale="ru-RU",
        blocks=blocks,
        meta=DocumentMeta(confidence=0.9, kind=kind),
    )


def _corpus(module: ModuleType, documents: Sequence[ContentDocument]) -> object:
    return module.Corpus(documents=tuple(documents), skipped=0)


def _write_jsonl(path: Path, payloads: Sequence[str]) -> Path:
    path.write_text("\n".join(payloads) + "\n", encoding="utf-8")
    return path


def _payload(document: ContentDocument) -> str:
    return json.dumps({"schema": "assistant_turn_v1", "document": document.model_dump(mode="json")})


def test_golden_set_is_a_measurement_not_a_gesture() -> None:
    """Fewer than ten labelled documents would make a false-positive rate noise."""
    assert len(_GOLDEN) >= 10


@pytest.mark.parametrize("index", range(len(_GOLDEN)))
def test_golden_document_has_no_findings(index: int) -> None:
    """A legitimate answer must stay clean: this is the FP gate on the curated set."""
    assert ContentLint.run(_GOLDEN[index]).findings == ()


def test_every_rule_is_reported_even_without_hits() -> None:
    """A rule missing from a zero-hit report would look like a rule that passes."""
    module = _load_module()
    result = module.run_backtest(module.load_corpus(_GOLDEN_PATH))

    assert [rule.rule_id for rule in result.rules] == [rule.rule_id for rule in module.RULES]
    assert all(rule.documents_hit == 0 and rule.findings == 0 for rule in result.rules)


def test_share_is_computed_over_all_documents() -> None:
    """Hits over *evaluated* documents, not over hits — the usual denominator trap."""
    module = _load_module()
    marked = _doc(ParagraphBlock(text="## Итоги"))
    clean = _doc(ParagraphBlock(text="Встреча перенесена."))

    result = module.run_backtest(_corpus(module, [marked, clean, clean, clean]))

    residue = next(rule for rule in result.rules if rule.rule_id == "markdown_residue")
    assert (residue.documents_hit, residue.findings) == (1, 1)
    assert result.share("markdown_residue") == pytest.approx(0.25)
    assert result.share("unknown_rule") == 0.0


def test_findings_count_repeats_while_documents_hit_do_not() -> None:
    """One answer with two leaking blocks is one affected answer, two defects."""
    module = _load_module()
    twice = _doc(
        ParagraphBlock(text="## Итоги"),
        ParagraphBlock(text="## Рекомендации"),
    )

    result = module.run_backtest(_corpus(module, [twice, _doc(ParagraphBlock(text="Текст."))]))

    residue = next(rule for rule in result.rules if rule.rule_id == "markdown_residue")
    assert (residue.documents_hit, residue.findings) == (1, 2)


def test_kind_breakdown_uses_the_persisted_axis() -> None:
    """``meta.kind`` is persisted; the intent's ``response_shape`` is not, so no join."""
    module = _load_module()
    documents = [
        _doc(ParagraphBlock(text="## Итоги"), kind="report"),
        _doc(ParagraphBlock(text="## Итоги"), kind="analysis"),
        _doc(ParagraphBlock(text="## Итоги"), kind="analysis"),
    ]

    result = module.run_backtest(_corpus(module, documents))

    residue = next(rule for rule in result.rules if rule.rule_id == "markdown_residue")
    assert dict(residue.by_kind) == {"analysis": 2, "report": 1}


def test_high_share_trigger_is_strictly_greater_than_the_threshold() -> None:
    """Exactly 5 % stays out of the review list; 10 % does not."""
    module = _load_module()
    flagged = _doc(ParagraphBlock(text="## Итоги"))
    clean = _doc(ParagraphBlock(text="Текст."))

    at_boundary = module.run_backtest(_corpus(module, [flagged, *[clean] * 19]))
    above = module.run_backtest(_corpus(module, [flagged, flagged, *[clean] * 18]))

    assert module.high_share_rules(at_boundary) == ()
    assert [rule.rule_id for rule in module.high_share_rules(above)] == ["markdown_residue"]


def test_loader_counts_what_it_could_not_validate(tmp_path: Path) -> None:
    """A silent skip would understate every share, so unparsable lines are reported."""
    module = _load_module()
    path = _write_jsonl(
        tmp_path / "turns.jsonl",
        [_payload(_doc(ParagraphBlock(text="Текст."))), "{}", "{not json"],
    )

    corpus = module.load_corpus(path)

    assert len(corpus.documents) == 1
    assert corpus.skipped == 2


def test_golden_measurement_reports_every_hit_as_false_positive() -> None:
    """The labelled side of the measurement counts documents, not findings."""
    module = _load_module()
    leaky = _doc(ParagraphBlock(text="## Итоги"), ParagraphBlock(text="## Выводы"))

    golden = module.measure_golden(_corpus(module, [leaky, _doc(ListBlock(items=(ListItem(text="Пункт"),)))]))

    assert (golden.documents, golden.documents_hit, golden.findings) == (2, 1, 2)
    assert golden.false_positive_rate == pytest.approx(0.5)
    assert dict(golden.by_rule) == {"markdown_residue": 1}


def test_main_writes_the_report_and_survives_a_missing_corpus(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No corpus is a normal state offline: report the absence, do not fail the run."""
    module = _load_module()
    turns = _write_jsonl(tmp_path / "turns.jsonl", [_payload(_doc(ParagraphBlock(text="## Итоги")))])
    report = tmp_path / "report.json"

    assert module.main(["--turns", str(turns), "--golden", str(_GOLDEN_PATH), "--json", str(report)]) == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["documents"] == 1
    assert payload["golden"]["false_positive_rate"] == 0.0
    assert payload["review_candidates"] == ["markdown_residue"]

    missing = tmp_path / "absent.jsonl"
    assert module.main(["--turns", str(missing), "--json", str(tmp_path / "other.json")]) == 0
    assert "turns file not found" in capsys.readouterr().out
