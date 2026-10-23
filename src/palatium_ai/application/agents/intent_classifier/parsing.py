# src/palatium_ai/application/agents/intent_classifier/parsing.py

"""Deterministic parsing for IntentClassifier LLM JSON output."""

from __future__ import annotations

from typing import cast

from palatium_ai.domain.agents.intent import IntentClassifierOutput, TaskKind, UnderspecificationKind
from palatium_ai.domain.agents.user_choice_intent import UserChoiceIntentPolicy
from palatium_ai.domain.llm.json_codec import loads_llm_json
from palatium_ai.domain.policies.grounding import GroundingPolicy
from palatium_ai.domain.policies.memory_mutation import MemoryMutationPolicy
from palatium_ai.domain.policies.shape import ShapeRecipePolicy
from palatium_ai.domain.policies.transform import TransformPolicy
from palatium_ai.domain.policies.types import (
    ATTACHMENT_FOCUS_DEFAULT,
    FILE_REFERENCE_DEFAULT,
    AttachmentFocus,
    AttachmentKind,
    AttachmentScope,
    FileReferenceKind,
    GroundingMode,
    MemoryMutationKind,
    TransformationKind,
)

_VALID_TASK_KINDS: frozenset[str] = frozenset(
    {
        "capability_discovery",
        "knowledge_request",
        "multi_step_workflow",
        "tool_execution",
        "response_formatting",
        "social_conversation",
        "clarification_needed",
    },
)

_VALID_UNDERSPEC: frozenset[str] = frozenset({"none", "open_text", "discrete_choice"})
_VALID_MEMORY_MUTATIONS: frozenset[str] = frozenset({"none", "save", "forget"})
_VALID_ATTACHMENT_SCOPES: frozenset[str] = frozenset({"auto", "all", "single"})
_VALID_ATTACHMENT_KINDS: frozenset[str] = frozenset({"any", "image", "document"})
_VALID_ATTACHMENT_FOCUS: frozenset[str] = frozenset({"current_uploads", "none"})


def parse_classifier_output(raw_content: str, *, has_thread_files: bool = False) -> IntentClassifierOutput:
    """Parse JSON LLM response into IntentClassifierOutput.

    ``has_thread_files`` is the structural precondition for the ``thread_file`` axis:
    a re-read can only target a file the dialog actually holds, so the label is
    down-coerced to ``none`` otherwise (code > model prose, 055).
    """
    payload = loads_llm_json(raw_content)
    if not isinstance(payload, dict):
        msg = "Intent classifier JSON must be an object"
        raise ValueError(msg)
    task_kind = _coerce_task_kind(payload.get("task_kind"))
    requires_mcp = bool(payload.get("requires_mcp", False))
    if task_kind == "social_conversation":
        requires_mcp = False
    raw_capabilities = payload.get("candidate_capabilities", [])
    capabilities: tuple[str, ...] = (
        tuple(str(item) for item in raw_capabilities if str(item)) if isinstance(raw_capabilities, list) else ()
    )
    grounding = _coerce_grounding(payload.get("grounding"), task_kind=task_kind, capabilities=capabilities)
    grounding_reason = str(payload.get("grounding_reason") or payload.get("reason") or "")[:500]
    transformation = _coerce_transformation(payload.get("transformation"))
    file_reference = _coerce_file_reference(
        payload.get("file_reference"),
        has_thread_files=has_thread_files,
    )
    memory_mutation, memory_text, memory_key = _coerce_memory_mutation(payload)
    attachment_scope = _coerce_attachment_scope(payload.get("attachment_scope"))
    attachment_kind = _coerce_attachment_kind(payload.get("attachment_kind"))
    attachment_focus = _coerce_attachment_focus(payload.get("attachment_focus"))
    requires_user_choice = _coerce_bool_flag(payload.get("requires_user_choice"))
    underspecification_kind = _coerce_underspecification_kind(payload)
    if memory_mutation != "none":
        # A mutation is an execution, never a menu: the gate owns the HITL card (020).
        requires_user_choice = False
        underspecification_kind = "none"
        task_kind = "tool_execution"
        requires_mcp = True

    return UserChoiceIntentPolicy.normalize(
        IntentClassifierOutput(
            task_kind=task_kind,
            requires_mcp=requires_mcp,
            requires_user_choice=requires_user_choice,
            underspecification_kind=underspecification_kind,
            candidate_capabilities=capabilities,
            grounding=grounding,
            grounding_reason=grounding_reason,
            transformation=transformation,
            file_reference=file_reference,
            attachment_scope=attachment_scope,
            attachment_kind=attachment_kind,
            attachment_focus=attachment_focus,
            response_shape=ShapeRecipePolicy.coerce(payload.get("response_shape")),
            memory_mutation=memory_mutation,
            memory_text=memory_text,
            memory_key=memory_key,
            confidence=float(payload.get("confidence", 0.0)),
            reasoning=str(payload.get("reasoning", "No reasoning provided")),
        ),
    )


def _coerce_memory_mutation(payload: dict[str, object]) -> tuple[MemoryMutationKind, str, str]:
    """Validate the mutation axis; a label without a payload is not actionable.

    Code owns the invariant (055): a mutation always routes as a tool execution with
    a bounded statement + entry-key hint, so the gate can stage a HITL card instead of
    a worker claiming the write.
    """
    raw = payload.get("memory_mutation")
    kind: MemoryMutationKind = (
        cast("MemoryMutationKind", raw.strip()) if isinstance(raw, str) and raw.strip() in _VALID_MEMORY_MUTATIONS else "none"
    )
    if kind == "none":
        return "none", "", ""
    text = MemoryMutationPolicy.coerce_text(payload.get("memory_text"))
    if not text:
        return "none", "", ""
    return kind, text, MemoryMutationPolicy.coerce_key(payload.get("memory_key"), text=text)


def _coerce_attachment_scope(raw: object) -> AttachmentScope:
    """Unknown/absent labels fall back to ``auto`` — never to a HITL guess (055)."""
    if isinstance(raw, str) and raw.strip() in _VALID_ATTACHMENT_SCOPES:
        return cast("AttachmentScope", raw.strip())
    return "auto"


def _coerce_attachment_kind(raw: object) -> AttachmentKind:
    """Unknown/absent labels mean "no modality filter" — selection stays deterministic."""
    if isinstance(raw, str) and raw.strip() in _VALID_ATTACHMENT_KINDS:
        return cast("AttachmentKind", raw.strip())
    return "any"


def _coerce_attachment_focus(raw: object) -> AttachmentFocus:
    """Absent/unknown labels keep the uploads in scope (fail-safe: evidence > silence)."""
    if isinstance(raw, str) and raw.strip() in _VALID_ATTACHMENT_FOCUS:
        return cast("AttachmentFocus", raw.strip())
    return ATTACHMENT_FOCUS_DEFAULT


def _coerce_bool_flag(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes"}
    return False


def _coerce_underspecification_kind(payload: dict[str, object]) -> UnderspecificationKind:
    raw = payload.get("underspecification_kind")
    if isinstance(raw, str) and raw.strip() in _VALID_UNDERSPEC:
        return cast("UnderspecificationKind", raw.strip())
    return "none"


def _coerce_task_kind(value: object) -> TaskKind:
    """Unknown labels take the default answer path — never a clarification (055)."""
    if isinstance(value, str) and value.strip() in _VALID_TASK_KINDS:
        return cast("TaskKind", value.strip())
    return "knowledge_request"


def _coerce_grounding(
    value: object,
    *,
    task_kind: TaskKind,
    capabilities: tuple[str, ...],
) -> GroundingMode:
    """Invalid/missing → optional. Soft defaults for social/compose when omitted."""
    mode = GroundingPolicy.coerce_mode(value)
    if isinstance(value, str) and value.strip() in {"required", "optional", "none"}:
        return mode
    if task_kind == "social_conversation":
        return "none"
    caps = {c.strip().lower() for c in capabilities if c.strip()}
    if "compose" in caps:
        return "none"
    return mode


def _coerce_transformation(value: object) -> TransformationKind:
    return TransformPolicy.coerce(value)


def _coerce_file_reference(value: object, *, has_thread_files: bool) -> FileReferenceKind:
    """Unknown labels / absent thread files → ``none`` (never a storage read by guess)."""
    if not has_thread_files:
        return FILE_REFERENCE_DEFAULT
    if isinstance(value, str) and value.strip() == "thread_file":
        return "thread_file"
    return FILE_REFERENCE_DEFAULT
