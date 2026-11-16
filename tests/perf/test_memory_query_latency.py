# tests/perf/test_memory_query_latency.py

"""Memory query p95 against a real pgvector cluster (M9 step 1; rules 060, 075, 080).

Rule 060 pins ``query p95 < 200 ms`` as an SLO target that has to be *established by eval*,
not assumed. That baseline was the last missing piece of M9 step 1: the histogram
(``palatium_memory_query_duration_seconds``) is exported in production, but no gate ever
looked at a real Postgres plan, so the cost of the hybrid path was unknown.

``pytest -m slow``, deliberately outside the pull-request path: the number only exists
against a cluster.

**Why an absolute budget and not a p95 ratio between corpus sizes.**
``tests/perf/test_hot_path_scaling.py`` explains why wall-clock ratios make bad gates, and a
stopwatch on a shared runner is exactly that. Comparing p95 at 100 vs 400 rows would fire on
a linear function the first time the runner is busy. The budget here is the SLO number from
rule 060 — a product promise, not a machine-relative ratio. Recorded baseline on the machine
this was calibrated on (Windows + Docker Desktop, the slowest environment in our matrix):
p95 117.5 ms / p50 98.4 ms at 400 rows. A red run therefore means "the SLO is unmet here" or
"the path regressed" — both actionable — and the failure message carries the measured p95/p50
with the corpus size, so the nightly log shows a trend instead of a bare verdict.

**Why the statement count as a second gate.** The budget is a stopwatch and stopwatches are
noisy. Counting ``SELECT`` statements per search is exact and machine-independent: the hybrid
path issues a fixed number of statements whatever the corpus size, and an N+1 regression
changes that number immediately while latency only hints at it. Structure and cost are
pinned separately, so a green run means both.

Runs in the ``memory-query-latency`` job of ``.github/workflows/perf-nightly.yml`` with
``PALATIUM_REQUIRE_DB=1``: a lost ``DATABASE_URL`` is red there, not a silent skip (075).
"""

from __future__ import annotations

import hashlib
import math
import struct
import time

from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from sqlalchemy import delete, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from palatium_ai.core.types.embeddings import MEMORY_EMBEDDING_DIM
from palatium_ai.infrastructure.database.models.memory_entry import MemoryEntryORM
from palatium_ai.infrastructure.database.rls import set_rls_user_scope
from palatium_ai.infrastructure.memory.postgres_memory_port import PostgresMemoryPort
from tests.support.database import database_url_or_skip

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.slow

# Control width vs measurement width. Latency is only measured at the large corpus; the
# narrow one exists to prove the statement count does not follow the row count.
_CORPUS_SMALL = 100
_CORPUS_LARGE = 400
# Platform ``search_memory`` default (rule 070), not a tuned value.
_LIMIT = 8
# Nearest-rank p95 on 25 samples is the 24th: one scheduling outlier cannot fail the job.
_SAMPLES = 25
_P95 = 0.95
# Rule 060 SLO. Recorded baseline on this test: p95 117.5 ms / p50 98.4 ms at 400 rows on
# Windows + Docker Desktop (calibrated there). Red means the SLO is unmet on that machine or
# the path regressed — both actionable.
_QUERY_P95_BUDGET_SECONDS = 0.200
# Fixed steps of the hybrid path: FTS + exact cosine, each in its own RLS-scoped session
# (one ``set_config`` roundtrip per session). Never one per candidate row — that is the gate;
# a future consolidation into a single session lowers this number and still passes.
_MAX_SELECT_STATEMENTS_PER_SEARCH = 4

_TOPICS = ("budget", "incident", "onboarding", "deploy", "retention")
# Each query matches a strict subset of the corpus through FTS, so the hybrid path is what
# gets measured instead of the token-overlap fallback.
_QUERIES = ("budget", "incident notes", "retention")

_EMBEDDING_SALT = b"palatium-perf-embeddings"


class _DeterministicEmbeddings:
    """4096-d stand-in with no provider call.

    The eval is about pgvector's exact-cosine cost at the production dimension (060), so the
    vector must be real and the provider must not be: a network embedding would measure the
    gateway, not the query.
    """

    async def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        return [_pseudo_vector(item) for item in texts]


def _pseudo_vector(item: str) -> list[float]:
    """Stable pseudo-random vector in [-1, 1): same text → same vector, every run."""
    digest = hashlib.shake_256(_EMBEDDING_SALT + item.encode("utf-8")).digest(MEMORY_EMBEDDING_DIM * 2)
    return [value / 32768.0 for value in struct.unpack(f"<{MEMORY_EMBEDDING_DIM}h", digest)]


class _SelectCounter:
    """Counts ``SELECT`` statements executed by the engine — structure, not timing."""

    def __init__(self) -> None:
        self._statements: list[str] = []

    def __call__(
        self,
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            self._statements.append(statement)

    def reset(self) -> None:
        self._statements.clear()

    @property
    def count(self) -> int:
        return len(self._statements)


def _entry_text(index: int) -> str:
    return f"perf corpus entry {index} about {_TOPICS[index % len(_TOPICS)]} and review notes"


async def _seed(port: PostgresMemoryPort, user_id: str, size: int) -> tuple[str, ...]:
    """One namespace per corpus width: separate users keep the two measurements independent."""
    namespace = ("user", user_id)
    for index in range(size):
        await port.put(
            namespace=namespace,
            key=f"perf-{index}",
            value={"kind": "fact", "text": _entry_text(index), "confidence": 0.5 + (index % 5) / 10.0},
        )
    return namespace


async def _latencies(port: PostgresMemoryPort, namespace: tuple[str, ...]) -> list[float]:
    """Per-search wall clock, after a warm-up that pays for the pool and prepared plans."""
    for query in _QUERIES:
        await port.search(namespace=namespace, query=query, limit=_LIMIT)
    samples: list[float] = []
    for index in range(_SAMPLES):
        query = _QUERIES[index % len(_QUERIES)]
        started = time.perf_counter()
        hits = await port.search(namespace=namespace, query=query, limit=_LIMIT)
        samples.append(time.perf_counter() - started)
        assert hits, f"query {query!r} matched nothing: the hybrid path was not measured"
    return samples


async def _statements_per_search(port: PostgresMemoryPort, namespace: tuple[str, ...], counter: _SelectCounter) -> int:
    """SQL roundtrips of exactly one search call."""
    counter.reset()
    await port.search(namespace=namespace, query=_QUERIES[0], limit=_LIMIT)
    return counter.count


def _p95(samples: Sequence[float]) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(_P95 * len(ordered)) - 1)]


def _median(samples: Sequence[float]) -> float:
    ordered = sorted(samples)
    return ordered[len(ordered) // 2]


async def _purge(engine: AsyncEngine, user_ids: Sequence[str]) -> None:
    """Remove this run's rows: unique user ids already isolate the run, this keeps the DB tidy."""
    async with AsyncSession(engine) as session:
        for user_id in user_ids:
            await set_rls_user_scope(session, user_id)
            await session.execute(delete(MemoryEntryORM).where(MemoryEntryORM.user_id == user_id))
        await session.commit()


@pytest.mark.asyncio()
async def test_memory_query_p95_fits_the_slo_budget_on_pgvector() -> None:
    url = database_url_or_skip(owner="tests/perf (memory query latency)")
    engine = create_async_engine(url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    port = PostgresMemoryPort(session_factory, embeddings=_DeterministicEmbeddings())
    counter = _SelectCounter()
    event.listen(engine.sync_engine, "before_cursor_execute", counter)
    run_id = uuid4().hex[:12]
    small_user = f"perf-small-{run_id}"
    large_user = f"perf-large-{run_id}"
    seeded = False

    try:
        small_namespace = await _seed(port, small_user, _CORPUS_SMALL)
        large_namespace = await _seed(port, large_user, _CORPUS_LARGE)
        seeded = True

        small_statements = await _statements_per_search(port, small_namespace, counter)
        large_statements = await _statements_per_search(port, large_namespace, counter)
        large_samples = await _latencies(port, large_namespace)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", counter)
        if seeded:  # a failed seed (no schema) must surface as itself, not as a purge error
            await _purge(engine, (small_user, large_user))
        await engine.dispose()

    large_p95 = _p95(large_samples)
    assert large_p95 > 0, "timer observed nothing: perf_counter granularity broke the measurement"
    assert large_p95 <= _QUERY_P95_BUDGET_SECONDS, (
        f"memory query p95 {large_p95 * 1000:.1f} ms at {_CORPUS_LARGE} rows exceeds the "
        f"{_QUERY_P95_BUDGET_SECONDS * 1000:.0f} ms SLO budget of rule 060 "
        f"(p50 {_median(large_samples) * 1000:.1f} ms, {_SAMPLES} samples, limit={_LIMIT})"
    )

    assert small_statements == large_statements, (
        f"SELECT count grew with the corpus ({small_statements} at {_CORPUS_SMALL} rows → "
        f"{large_statements} at {_CORPUS_LARGE}): the hybrid path became per-row (N+1)"
    )
    assert large_statements <= _MAX_SELECT_STATEMENTS_PER_SEARCH, (
        f"one search issued {large_statements} SELECT statements, at most "
        f"{_MAX_SELECT_STATEMENTS_PER_SEARCH} expected (FTS + exact cosine, each with its "
        "RLS scope); more means the hybrid path started talking to the DB per candidate"
    )
