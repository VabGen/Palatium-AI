"""Shared, typed helpers for the read-only Formatter diagnostic scripts.

``measure_structure_divergence``, ``measure_verbatim_parse``,
``measure_structure_fidelity`` and ``measure_writer_enrichment`` inspect the same
artifacts. Checkpoint loading, block flattening and percentile math live here so a
fix lands for all of them at once — private copies had drifted apart and kept
breaking each other (duplicate ``Turn``, three flatteners, raw ``dict`` blocks).

Read-only: no writes besides the report artifacts the callers publish. Requires the
local compose Postgres on host port 5434.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import TypeAdapter

from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput, FormatterTaskResult
from palatium_ai.domain.agents.researcher import ResearcherTaskResult
from palatium_ai.domain.content import (
    CalloutBlock,
    CodeBlock,
    ContentBlock,
    ContentDocument,
    HeadingBlock,
    KeyValueBlock,
    ListBlock,
    ParagraphBlock,
    StepsBlock,
    TableBlock,
)
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.policies.structure_divergence import (
    StructureDivergence,
    measure_structure_divergence,
)

#: Local compose Postgres (host port 5434), read-only.
CHECKPOINT_DSN = "postgresql://postgres:1234@localhost:5434/postgres"

ARTIFACTS_DIR = Path("artifacts")
VERBATIM_REPORT_PATH = ARTIFACTS_DIR / "verbatim_parse_report.json"
ENRICHMENT_REPORT_PATH = ARTIFACTS_DIR / "enrichment_report.json"
RECALL_TAIL_REPORT_PATH = ARTIFACTS_DIR / "recall_tail_report.json"

#: Below this token recall a turn counts as information loss (shared by the scripts
#: that read the same report, so the verdicts cannot disagree).
RECALL_GATE = 0.99

#: Ignore deltas that span a gap between turns instead of a single node.
MAX_NODE_SECONDS = 600.0

_BLOCKS_ADAPTER: TypeAdapter[tuple[ContentBlock, ...]] = TypeAdapter(tuple[ContentBlock, ...])


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile; ``values`` must be non-empty."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))]


def norm(text: str) -> str:
    """Collapse every whitespace run into a single space."""
    return " ".join(text.split())


def block_parts(block: ContentBlock) -> tuple[str, ...]:
    """Normalized prose fragments of one block (``kv``/``steps`` keep ``label=value``)."""
    match block:
        case ParagraphBlock() | HeadingBlock():
            return (norm(block.text),)
        case CalloutBlock():
            return (norm(block.title or ""), norm(block.body))
        case CodeBlock():
            return (norm(block.content),)
        case ListBlock():
            return tuple(norm(item.text) for item in block.items)
        case KeyValueBlock():
            return tuple(f"{norm(item.label)}={norm(item.value)}" for item in block.items)
        case StepsBlock():
            return tuple(f"{norm(item.title)}={norm(item.body)}" for item in block.items)
        case TableBlock():
            cells = (*block.columns, *(cell for row in block.rows for cell in row))
            return tuple(norm(cell) for cell in cells)
        case _:
            # Formula/chart/widget/divider carry no prose to compare against.
            return ()


def blocks_text(blocks: Iterable[ContentBlock]) -> str:
    """Flatten blocks into one normalized string for token-level comparison."""
    return norm(" ".join(" ".join(block_parts(block)) for block in blocks))


def parse_blocks(payload: object) -> tuple[ContentBlock, ...]:
    """Validate a JSON block list (report artifact) back into typed blocks."""
    return _BLOCKS_ADAPTER.validate_python(payload)


def token_recall(source_text: str, candidate_text: str) -> float:
    """Share of the ``source_text`` token multiset that survives in ``candidate_text``.

    Token multiset (not substring) so that re-splitting one paragraph into two
    blocks is not reported as information loss.
    """
    source = Counter(norm(source_text).split())
    total = sum(source.values())
    if not total:
        return 1.0
    candidate = Counter(norm(candidate_text).split())
    kept = sum(min(count, candidate.get(token, 0)) for token, count in source.items())
    return kept / total


def token_novelty(worker_text: str, formatter_text: str) -> float:
    """Share of formatter tokens the worker draft did not contain (case-insensitive)."""
    worker = Counter(norm(worker_text).lower().split())
    formatter = Counter(norm(formatter_text).lower().split())
    total = sum(formatter.values())
    if not total:
        return 0.0
    new_tokens = sum(max(0, count - worker.get(token, 0)) for token, count in formatter.items())
    return new_tokens / total


def formatter_task_input() -> FormatterInput:
    """Minimal valid input for the deterministic renderer (no LLM call)."""
    packet = ContextPacket(
        task_id="measure",
        user_text="measure",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="answer",
        requires_mcp=False,
        execution_plan=ToolExecutionPlan(
            strategy="reason_only",
            requires_tool_call=False,
            rationale="measurement",
        ),
        context_summary="measurement",
    )
    return FormatterInput(task_id="measure", context_packet=packet, response_locale="ru-RU")


@dataclass(frozen=True, slots=True)
class Turn:
    """One paired worker draft + final document recovered from the checkpoint log."""

    task_id: str
    thread_id: str
    summary: str
    document: ContentDocument
    result: StructureDivergence
    researcher_seconds: float | None
    formatter_seconds: float | None

    @property
    def divergence(self) -> float:
        return self.result.structure_divergence

    @property
    def coverage(self) -> float:
        return self.result.block_coverage


@dataclass(frozen=True, slots=True)
class _Checkpoint:
    thread_id: str
    ts: datetime
    execution: ResearcherTaskResult | None
    formatted: FormatterTaskResult | None


def _load_checkpoints(limit: int) -> list[_Checkpoint]:
    rows: list[_Checkpoint] = []
    with PostgresSaver.from_conn_string(CHECKPOINT_DSN) as saver:
        for item in saver.list(None, limit=limit):
            values = item.checkpoint.get("channel_values", {})
            # ``configurable`` is optional in RunnableConfig (TypedDict, total=False),
            # so it must not be subscripted directly.
            configurable = item.config.get("configurable") or {}
            execution = values.get("execution")
            formatted = values.get("formatted")
            rows.append(
                _Checkpoint(
                    thread_id=str(values.get("thread_id") or configurable.get("thread_id") or ""),
                    ts=datetime.fromisoformat(str(item.checkpoint["ts"])),
                    execution=execution if isinstance(execution, ResearcherTaskResult) else None,
                    formatted=formatted if isinstance(formatted, FormatterTaskResult) else None,
                )
            )
    return rows


def _node_timings(rows: Sequence[_Checkpoint]) -> dict[str, dict[str, float]]:
    """Map task_id -> {researcher, formatter} seconds from checkpoint timestamps.

    The delta is attributed to the node whose output the checkpoint carries, so a
    turn that skipped the researcher does not bill its gap to the formatter.
    """
    timings: dict[str, dict[str, float]] = defaultdict(dict)
    by_thread: dict[str, list[_Checkpoint]] = defaultdict(list)
    for row in rows:
        by_thread[row.thread_id].append(row)
    for thread_rows in by_thread.values():
        thread_rows.sort(key=lambda row: row.ts)
        for index, row in enumerate(thread_rows):
            if index == 0:
                continue
            seconds = (row.ts - thread_rows[index - 1].ts).total_seconds()
            if not 0 < seconds <= MAX_NODE_SECONDS:
                continue
            if row.execution is not None and row.execution.output is not None:
                timings[str(row.execution.task_id)].setdefault("researcher", seconds)
            if row.formatted is not None and row.formatted.output is not None:
                timings[str(row.formatted.task_id)].setdefault("formatter", seconds)
    return timings


def collect_turns(limit: int = 2500) -> list[Turn]:
    """Terminal turns: ``execution`` and ``formatted`` set for the same task_id.

    State channels persist across turns in a thread, so a turn that skipped the
    researcher keeps the previous ``execution``; only same-task pairs are real.
    """
    rows = _load_checkpoints(limit)
    timings = _node_timings(rows)
    turns: list[Turn] = []
    seen: set[str] = set()
    for row in rows:
        execution = row.execution
        formatted = row.formatted
        if execution is None or execution.output is None:
            continue
        if formatted is None or formatted.output is None:
            continue
        if formatted.task_id != execution.task_id:
            continue
        task_id = str(execution.task_id)
        if task_id in seen:
            continue
        seen.add(task_id)
        summary = execution.output.summary
        document = formatted.output
        timing = timings.get(task_id, {})
        turns.append(
            Turn(
                task_id=task_id,
                thread_id=row.thread_id,
                summary=summary,
                document=document,
                result=measure_structure_divergence(summary, document),
                researcher_seconds=timing.get("researcher"),
                formatter_seconds=timing.get("formatter"),
            )
        )
    return turns
