# src/palatium_ai/application/agents/evals/report.py

"""JSON-serializable eval suite report (075 CI artifacts)."""

from __future__ import annotations

import json

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class TaskEvalReport(BaseModel, frozen=True):
    task_id: str
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    details: str
    mode: str = Field(description="fixture | cassette | runtime")


class AgentEvalReport(BaseModel, frozen=True):
    agent: str
    score: float = Field(ge=0.0, le=1.0)
    passed: int = Field(ge=0)
    total: int = Field(ge=0)
    tasks: tuple[TaskEvalReport, ...] = ()
    details: tuple[str, ...] = ()


class EvalSuiteReport(BaseModel, frozen=True):
    schema_version: int = 1
    generated_at: str
    tolerance: float
    agents: tuple[AgentEvalReport, ...]

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.model_dump(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_reports(
        cls,
        reports: dict[str, AgentEvalReport],
        *,
        tolerance: float,
    ) -> EvalSuiteReport:
        return cls(
            generated_at=datetime.now(UTC).isoformat(),
            tolerance=tolerance,
            agents=tuple(reports[name] for name in sorted(reports)),
        )


def write_report(path: str, report: EvalSuiteReport) -> None:
    from pathlib import Path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report.to_json(), encoding="utf-8")
