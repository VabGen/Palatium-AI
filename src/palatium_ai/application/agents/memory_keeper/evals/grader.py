# src/palatium_ai/application/agents/memory_keeper/evals/grader.py

"""Deterministic grader for MemoryKeeper fact extraction eval tasks."""

from __future__ import annotations

from typing import Any

from palatium_ai.application.agents.memory_keeper.parsing import parse_memory_keeper_output
from palatium_ai.domain.agents.evals import GradeResult, failed, passed, resolve_output


class MemoryKeeperGrader:
    kind = "deterministic"

    async def grade(self, task: dict[str, Any], output: dict[str, Any]) -> GradeResult:
        expect = task.get("expect")
        if not isinstance(expect, dict):
            return failed(0.0, details="invalid expect")

        resolved = resolve_output(task, output)
        if not resolved and isinstance(task.get("cassette_parse"), str):
            parsed = parse_memory_keeper_output(task["cassette_parse"])
            resolved = {
                "facts": [
                    {"text": fact.text, "kind": fact.kind, "confidence": fact.confidence} for fact in parsed.facts
                ]
            }

        facts = resolved.get("facts", [])
        if not isinstance(facts, list):
            return failed(0.0, details="facts must be a list")

        min_facts = expect.get("min_facts", 1)
        if len(facts) < int(min_facts):
            return failed(0.0, details=f"facts {len(facts)} < min {min_facts}")

        kind = expect.get("kind")
        if isinstance(kind, str) and not any(isinstance(item, dict) and item.get("kind") == kind for item in facts):
            return failed(0.0, details=f"no fact with kind={kind}")

        return passed(1.0, details="memory keeper facts ok")


grader = MemoryKeeperGrader()
