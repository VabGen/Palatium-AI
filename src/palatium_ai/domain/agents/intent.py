# src/palatium_ai/domain/agents/intent.py

"""Контракты агента IntentClassifier."""

from typing import Literal

from pydantic import BaseModel, Field

from .contracts import TaskResult

TaskKind = Literal[
    "capability_discovery",
    "knowledge_request",
    "multi_step_workflow",
    "tool_execution",
    "response_formatting",
    "social_conversation",
    "clarification_needed",
]


class IntentClassifierInput(BaseModel):
    """Вход IntentClassifier (текст + continuity hints; history не дампим)."""

    model_config = {"frozen": True}

    task_id: str
    text: str = Field(min_length=1, max_length=32_000)
    continuation_kind: Literal["format", "answer", "new_topic", "clarify"] | None = None
    has_prior_dialog: bool = False


class IntentClassifierOutput(BaseModel):
    """Структурированный результат классификации."""

    model_config = {"frozen": True}

    task_kind: TaskKind
    requires_mcp: bool
    requires_user_choice: bool = Field(
        default=False,
        description=(
            "True when the user must pick among exclusive alternatives "
            "(topic/type/option menu) before work proceeds — HITL cards, not a text list."
        ),
    )
    candidate_capabilities: tuple[str, ...] = Field(default_factory=tuple)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1)


class IntentTaskResult(TaskResult):
    """TaskResult с типизированным output для IntentClassifier."""

    output: IntentClassifierOutput | None = None
