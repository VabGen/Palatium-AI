"""Hot-path complexity guards: an accidental O(n²) must fail here, not in production (080).

``pytest -m slow`` (``make perf``), deliberately outside the pull-request path.

**Why instruction counts, not milliseconds.** The first version of this file measured
wall-clock ratios and was worthless on the machine it was written on: ``time.perf_counter``
pushed a linear function to a 12x "regression" because the runner was busy, and
``time.process_time`` has ~16 ms granularity on Windows, so a microsecond-scale call
measured a flat 0. A gate that fires on a linear function teaches people to ignore it.

``sys.monitoring`` counts executed **bytecode instructions**: exact, deterministic and
machine-independent. Same input → same number, every run, on every OS. It counts Python-level
work only, which matches exactly the defect rule 080 names — a nested Python loop executes
~n² instructions, while a single C-level ``sorted()``/``len()`` stays flat (the counter
cannot see inside it). That limit is stated per test rather than papered over: a function
that delegates to C primitives shows *sub*-linear instruction growth, and the assertion here
is "no faster than linear growth", not "exactly linear".
"""

from __future__ import annotations

import sys

from collections.abc import Callable, Iterator

import pytest

from palatium_ai.domain.policies.compact import CompactPolicy
from palatium_ai.infrastructure.memory.postgres_memory_port import merge_hybrid_scores

pytestmark = pytest.mark.slow

_MONITORING = sys.monitoring
_EVENTS = _MONITORING.events

_SCALE_FACTOR = 4
# Linear costs ``_SCALE_FACTOR`` instructions, quadratic ``_SCALE_FACTOR ** 2`` (= 16).
# 1.5 tolerates per-call constant overhead; a nested loop blows straight past it.
_LINEAR_TOLERANCE = 1.5
_MAX_RATIO = _LINEAR_TOLERANCE * _SCALE_FACTOR
# Lower bound for code that *is* Python-loop-bound: catches a counter that quietly died.
_MIN_RATIO = _SCALE_FACTOR / _LINEAR_TOLERANCE

# Small enough to stay instant, large enough that constant per-call overhead is noise:
# dedupe at n=250 is 11 051 instructions of which ~40 are constant.
_SMALL = 250

_Counted = Callable[[Callable[[], object]], int]


def _claim_tool_id() -> int:
    """Reserve a free ``sys.monitoring`` tool id, or skip: another tool owns this process."""
    for candidate in range(_MONITORING.PROFILER_ID, _MONITORING.PROFILER_ID + 6):
        try:
            _MONITORING.use_tool_id(candidate, "palatium-hot-path-counter")
        except ValueError:
            continue
        return candidate
    pytest.skip("no free sys.monitoring tool id: another profiler/coverage tool holds them")


@pytest.fixture(scope="module")
def instruction_counter() -> Iterator[_Counted]:
    """Count bytecode instructions executed by a callable.

    Module-scoped: the tool id is process-global, so one claim per module is both the
    cheapest and the only correct option.
    """
    tool_id = _claim_tool_id()

    def count_instructions(run: Callable[[], object]) -> int:
        executed = 0

        def on_instruction(_code: object, _offset: int) -> None:
            nonlocal executed
            executed += 1

        _MONITORING.register_callback(tool_id, _EVENTS.INSTRUCTION, on_instruction)
        _MONITORING.set_events(tool_id, _EVENTS.INSTRUCTION)
        try:
            run()
        finally:
            _MONITORING.set_events(tool_id, 0)
            _MONITORING.register_callback(tool_id, _EVENTS.INSTRUCTION, None)
        return executed

    yield count_instructions

    _MONITORING.free_tool_id(tool_id)


def _ratio(count_instructions: _Counted, build: Callable[[int], Callable[[], object]]) -> float:
    """Instruction growth from ``_SMALL`` to ``_SMALL * _SCALE_FACTOR`` input."""
    baseline = count_instructions(build(_SMALL))
    assert baseline > 0, "counter observed no instructions at all"
    return count_instructions(build(_SMALL * _SCALE_FACTOR)) / baseline


def _assert_at_most_linear(
    count_instructions: _Counted, build: Callable[[int], Callable[[], object]], label: str
) -> float:
    """Fail when ``_SCALE_FACTOR``x input costs quadratic-order instructions."""
    ratio = _ratio(count_instructions, build)
    assert ratio <= _MAX_RATIO, f"{label} looks super-linear: {ratio:.2f}x instructions for {_SCALE_FACTOR}x input"
    return ratio


def _dialog(lines: int) -> str:
    """Deterministic dialog with a mix of unique and repeated turns."""
    return "\n".join(f"turn {index} — user asks question {index % 97}" for index in range(lines))


def test_counter_is_deterministic(instruction_counter: _Counted) -> None:
    """Identical input must cost an identical count — that is the whole point of the gate."""
    run = lambda: CompactPolicy.dedupe_exact_lines(_dialog(_SMALL))  # noqa: E731

    assert instruction_counter(run) == instruction_counter(run)


def test_counter_has_teeth_and_reports_linear_code_as_linear(instruction_counter: _Counted) -> None:
    """Prove what the counter can and cannot see, before trusting it on library code.

    A harness that silently stopped counting would make every assertion below pass for the
    wrong reason, so the two extremes are pinned here: a nested loop must fail loudly, and a
    single Python-level pass must be reported at exactly the linear ratio.
    """

    def python_loop(size: int) -> Callable[[], object]:
        items = list(range(size))

        def run() -> int:
            total = 0
            for item in items:  # one Python-level pass → linear instructions
                total += item
            return total

        return run

    def nested_loop(size: int) -> Callable[[], object]:
        items = list(range(size))

        def run() -> int:
            total = 0
            for outer in items:
                for inner in items:  # deliberate O(n²) — this is what must be caught
                    total += outer * inner
            return total

        return run

    with pytest.raises(AssertionError, match="super-linear"):
        _assert_at_most_linear(instruction_counter, nested_loop, "deliberate-quadratic")

    linear_ratio = _assert_at_most_linear(instruction_counter, python_loop, "deliberate-linear")
    assert linear_ratio >= _MIN_RATIO, f"counter under-reports Python work: {linear_ratio:.2f}x"


def test_dialog_dedupe_scales_linearly(instruction_counter: _Counted) -> None:
    """Exact-line dedupe is a set lookup per line (065.4) — never a scan of seen lines."""
    ratio = _assert_at_most_linear(
        instruction_counter,
        lambda lines: lambda: CompactPolicy.dedupe_exact_lines(_dialog(lines)),
        "dedupe_exact_lines",
    )

    assert ratio >= _MIN_RATIO, f"dedupe stopped doing per-line work: {ratio:.2f}x"


def test_hybrid_merge_scales_linearly(instruction_counter: _Counted) -> None:
    """FTS+vector merge is a dict insert per hit — a nested scan over hits would be n²."""

    def build(size: int) -> Callable[[], object]:
        # Same entry keys on both sides: the merge is expected to collapse duplicates,
        # which is the branch a naive implementation gets quadratic on.
        fts = [(f"entry-{index}", 0.5, {"text": f"doc {index}", "confidence": 0.9}) for index in range(size)]
        vector = [(f"entry-{index}", 0.7, {"text": f"doc {index}", "confidence": 0.8}) for index in range(size)]
        return lambda: merge_hybrid_scores(fts, vector, limit=20)

    ratio = _assert_at_most_linear(instruction_counter, build, "merge_hybrid_scores")

    assert ratio >= _MIN_RATIO, f"merge stopped doing per-hit work: {ratio:.2f}x"


def test_token_accounting_has_no_per_item_python_work(instruction_counter: _Counted) -> None:
    """``package_tokens`` must stay flat in instructions (065.5).

    It delegates to ``len()`` (C), so instruction growth is ~1x regardless of dialog size —
    and that is the property worth pinning: replacing the estimate with a Python loop over
    characters or parts would make the count jump with input size, which is the regression.
    Sub-linear is the expected result here, so only the upper bound is asserted.
    """

    def build(lines: int) -> Callable[[], object]:
        dialog = _dialog(lines)
        return lambda: CompactPolicy.package_tokens(dialog=dialog, goal="a goal", plan="a plan", last_results="results")

    ratio = _assert_at_most_linear(instruction_counter, build, "package_tokens")

    assert ratio <= _LINEAR_TOLERANCE, (
        f"package_tokens grew {ratio:.2f}x with {_SCALE_FACTOR}x input: it used to be a C-level length estimate"
    )
