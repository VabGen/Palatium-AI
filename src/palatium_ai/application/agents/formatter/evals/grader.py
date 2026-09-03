# src/palatium_ai/application/agents/formatter/evals/grader.py

"""Deterministic grader for Formatter ContentDocument eval tasks."""

from __future__ import annotations

from typing import Any

from palatium_ai.domain.agents.evals import failed, passed, resolve_output
from palatium_ai.domain.content import parse_content_document


class FormatterGrader:
    kind = "deterministic"

    async def grade(self, task: dict[str, Any], output: dict[str, Any]) -> Any:
        expect = task.get("expect")
        if not isinstance(expect, dict):
            return failed(0.0, details="invalid expect")

        resolved = resolve_output(task, output)
        if resolved:
            if resolved.get("schema_version") != expect.get("schema_version"):
                return failed(0.0, details="schema_version mismatch")
            min_blocks = expect.get("block_count_min")
            block_count = int(resolved.get("block_count", 0))
            if isinstance(min_blocks, int) and block_count < min_blocks:
                return failed(0.0, details=f"blocks {block_count} < min {min_blocks}")
            expected_status = expect.get("status")
            if isinstance(expected_status, str) and resolved.get("status") != expected_status:
                return failed(0.0, details=f"status: expected {expected_status!r}, got {resolved.get('status')!r}")
            return passed(1.0, details="formatter harness ok")

        payload = task.get("payload")
        if not isinstance(payload, dict):
            return failed(0.0, details="invalid payload or harness output")
        doc = parse_content_document(payload)
        if doc.schema_version != expect.get("schema_version"):
            return failed(0.0, details="schema_version mismatch")
        min_blocks = expect.get("block_count_min")
        if isinstance(min_blocks, int) and len(doc.blocks) < min_blocks:
            return failed(0.0, details=f"blocks {len(doc.blocks)} < min {min_blocks}")
        return passed(1.0, details="content document valid")


grader = FormatterGrader()
