# src/palatium_ai/domain/agents/intent.py

"""Контракты агента IntentClassifier."""

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.types import (
    ATTACHMENT_FOCUS_DEFAULT,
    ATTACHMENT_KIND_DEFAULT,
    ATTACHMENT_SCOPE_DEFAULT,
    FILE_REFERENCE_DEFAULT,
    GROUNDING_DEFAULT,
    MEMORY_MUTATION_DEFAULT,
    RESPONSE_SHAPE_DEFAULT,
    TRANSFORMATION_DEFAULT,
    AttachmentFocus,
    AttachmentKind,
    AttachmentModality,
    AttachmentScope,
    ContinuationKind,
    FileReferenceKind,
    GroundingMode,
    MemoryMutationKind,
    ResponseShape,
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
    #: Files attached to THIS turn (already resolved by the API). Gives the model the
    #: plurality it needs for ``attachment_scope`` without inventing a count (010).
    attachment_count: int = Field(default=0, ge=0)
    #: Modalities present in this turn ("image" / "document"), closed vocabulary.
    attachment_kinds: tuple[AttachmentModality, ...] = ()


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
    response_shape: ResponseShape = Field(
        default=RESPONSE_SHAPE_DEFAULT,
        description=(
            "Form of the answer body: auto (formatter chooses), comparison_table, "
            "document_analysis, plan, prose. Set when the user names a form or the "
            "deliverable is unambiguously one of these; never for social/clarification."
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
    attachment_scope: AttachmentScope = Field(
        default=ATTACHMENT_SCOPE_DEFAULT,
        description=(
            "Which current-turn attachments the ask targets: auto (no explicit "
            "plurality), all (explicitly the whole set), single (one file in the "
            "singular). With several matching files, single mints a file-choice card "
            "before any worker runs."
        ),
    )
    attachment_kind: AttachmentKind = Field(
        default=ATTACHMENT_KIND_DEFAULT,
        description=(
            "Modality filter for the ask: any, image (picture/scan/OCR), document "
            "(pdf/docx/xlsx/text). Selection is deterministic in code, not by the LLM."
        ),
    )
    attachment_focus: AttachmentFocus = Field(
        default=ATTACHMENT_FOCUS_DEFAULT,
        description=(
            "current_uploads | none. 'none' when the ask explicitly is NOT about the "
            "files uploaded in this turn (chitchat, a question about the dialog, an "
            "explicit «не про файлы»). The fenced text is then withheld from every "
            "prompt so the answer cannot quote a document the user set aside."
        ),
    )
    memory_mutation: MemoryMutationKind = Field(
        default=MEMORY_MUTATION_DEFAULT,
        description=(
            "none | save | forget. Explicit ask to write/delete a memory entry "
            "(«запомни …», «забудь …»). Routed to the memory gate, never answered by a "
            "worker: the mutation only happens through a HITL-approved MCP call."
        ),
    )
    memory_text: str = Field(
        default="",
        max_length=2_000,
        description=(
            "Payload for memory_mutation: the atomic fact to store (save) or the "
            "subject to delete (forget), taken from the user's ask. Empty otherwise."
        ),
    )
    memory_key: str = Field(
        default="",
        max_length=64,
        description=(
            "Optional stable latin key hint for the memory entry (e.g. db_port) so a "
            "later correction updates the same entry instead of adding a second fact."
        ),
    )
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1)


class IntentTaskResult(TaskResult):
    """TaskResult с типизированным output для IntentClassifier."""

    output: IntentClassifierOutput | None = None
