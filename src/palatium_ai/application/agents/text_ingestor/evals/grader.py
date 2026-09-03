# src/palatium_ai/application/agents/text_ingestor/evals/grader.py

"""Deterministic grader for TextIngestor chunking eval tasks."""

from __future__ import annotations

from typing import Any

from palatium_ai.domain.agents.evals import GradeResult, failed, passed, resolve_output


def _fail_status(expect: dict[str, Any], resolved: dict[str, Any]) -> GradeResult | None:
    status = expect.get("status")
    if isinstance(status, str) and resolved.get("status") != status:
        return failed(0.0, details=f"status {resolved.get('status')} != {status}")
    return None


def _fail_min_chunks(expect: dict[str, Any], resolved: dict[str, Any]) -> GradeResult | None:
    min_chunks = expect.get("min_chunks")
    if min_chunks is None:
        return None
    chunk_count = int(resolved.get("chunk_count", 0))
    if chunk_count < int(min_chunks):
        return failed(0.0, details=f"chunk_count {chunk_count} < min {min_chunks}")
    return None


def _fail_strategy(expect: dict[str, Any], resolved: dict[str, Any]) -> GradeResult | None:
    strategy = expect.get("strategy")
    if isinstance(strategy, str) and resolved.get("strategy") != strategy:
        return failed(0.0, details=f"strategy {resolved.get('strategy')} != {strategy}")
    return None


def _fail_prefixes(expect: dict[str, Any], resolved: dict[str, Any]) -> GradeResult | None:
    if expect.get("context_prefixes_applied") is True and not resolved.get("context_prefixes_applied"):
        return failed(0.0, details="context prefixes were not applied")
    min_prefixed = expect.get("min_prefixed_chunks")
    if min_prefixed is None:
        return None
    prefixed = int(resolved.get("prefixed_chunk_count", 0))
    if prefixed < int(min_prefixed):
        return failed(0.0, details=f"prefixed {prefixed} < min {min_prefixed}")
    return None


def _fail_max_chunk(expect: dict[str, Any], resolved: dict[str, Any]) -> GradeResult | None:
    max_chunk_chars = expect.get("max_chunk_chars")
    if max_chunk_chars is None:
        return None
    seen = int(resolved.get("max_chunk_chars_seen", 0))
    if seen > int(max_chunk_chars):
        return failed(0.0, details=f"max chunk {seen} > limit {max_chunk_chars}")
    return None


class TextIngestorGrader:
    kind = "deterministic"

    async def grade(self, task: dict[str, Any], output: dict[str, Any]) -> GradeResult:
        expect = task.get("expect")
        if not isinstance(expect, dict):
            return failed(0.0, details="invalid expect")

        resolved = resolve_output(task, output)
        if not resolved:
            return failed(0.0, details="missing output")

        for check in (
            _fail_status,
            _fail_min_chunks,
            _fail_strategy,
            _fail_prefixes,
            _fail_max_chunk,
        ):
            failure = check(expect, resolved)
            if failure is not None:
                return failure

        return passed(1.0, details="text ingestor chunks ok")


grader = TextIngestorGrader()
