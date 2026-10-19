# src/palatium_ai/domain/agents/intent.py

"""Контракты агента IntentClassifier."""

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.types import (
    FILE_REFERENCE_DEFAULT,
    GROUNDING_DEFAULT,
    TRANSFORMATION_DEFAULT,
    ContinuationKind,
    FileReferenceKind,
    GroundingMode,
    TaskKind,
    TransformationKind,
    UnderspecificationKind,
)

from .contracts import TaskResult

__all__ = [
    "IntentClassifierInput",
    "IntentClassifierOutput",
    "IntentTaskResult",
    "TaskKind",
    "UnderspecificationKind",
]


class IntentClassifierInput(BaseModel):
    """Вход IntentClassifier (текст + continuity hints; history не дампим)."""

    model_config = {"frozen": True}

    task_id: str
    text: str = Field(min_length=1, max_length=32_000)
    continuation_kind: ContinuationKind | None = None
    has_prior_dialog: bool = False
    #: Dialog already holds uploads (turn payload ids). Structural precondition for
    #: ``file_reference="thread_file"`` — a re-read can only target an existing file.
    has_thread_files: bool = False


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
    underspecification_kind: UnderspecificationKind = Field(
        default="none",
        description=(
            "none | open_text | discrete_choice. discrete_choice means a required "
            "parameter is missing and must be chosen from suggested alternatives "
            "via HITL cards before the main work runs."
        ),
    )
    candidate_capabilities: tuple[str, ...] = Field(default_factory=tuple)
    grounding: GroundingMode = Field(
        default=GROUNDING_DEFAULT,
        description=(
            "Need for external retrieval: required (cannot answer without user data), "
            "optional (try retrieve then degrade), none (reason without tools)."
        ),
    )
    grounding_reason: str = Field(
        default="",
        max_length=500,
        description="Brief rationale for grounding mode (not user-facing).",
    )
    transformation: TransformationKind = Field(
        default=TRANSFORMATION_DEFAULT,
        description=(
            "How to transform prior content when the ask is a format-continuation: "
            "restructure (layout/sections) vs expand/shorten/rewrite (content change). "
            "none when not a prior-transform ask."
        ),
    )
    file_reference: FileReferenceKind = Field(
        default=FILE_REFERENCE_DEFAULT,
        description=(
            "none | thread_file. 'thread_file' when the ask operates on a file already "
            "uploaded in this dialog (re-read it from storage) rather than on content "
            "fenced into the current turn. Identity is resolved in code, not by the model."
        ),
    )
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1)


class IntentTaskResult(TaskResult):
    """TaskResult с типизированным output для IntentClassifier."""

    output: IntentClassifierOutput | None = None
