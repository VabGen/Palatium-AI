# src/palatium_ai/application/agents/researcher/llm_research.py

"""LLM research path (no MCP tool call) for ResearcherAgent."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from palatium_ai.application.agents.researcher.config import (
    SUMMARY_MAX_CHARS,
    researcher_completion_budget,
    researcher_llm_config,
)
from palatium_ai.application.agents.researcher.outcomes import failure_output
from palatium_ai.application.agents.researcher.parsing import (
    parse_researcher_output,
    score_mcp_tool_confidence,
    unwrap_read_attachment_text,
)
from palatium_ai.application.agents.researcher.prompts import (
    RESEARCHER_SYSTEM_PROMPT,
    RESEARCHER_UNGROUNDED_SYSTEM_NOTE,
)
from palatium_ai.application.agents.skill_hydrate import hydrate_skill_references
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.contracts import AgentContext
from palatium_ai.domain.agents.messages import AgentOutput
from palatium_ai.domain.agents.researcher import ResearcherInput, ResearcherOutput
from palatium_ai.domain.content.page_markers import strip_page_markers
from palatium_ai.domain.llm.models import DocumentPart, ImagePart
from palatium_ai.domain.policies.file_reference import FileReferencePolicy
from palatium_ai.domain.policies.prompt_assembly import PromptAssemblyParts, PromptAssemblyPolicy
from palatium_ai.domain.policies.researcher_observation import ResearcherObservationPolicy

if TYPE_CHECKING:
    from palatium_ai.application.tools.executor import ToolExecutor
    from palatium_ai.domain.agents.agent_config import AgentConfig
    from palatium_ai.domain.ports.harness import HarnessPort
    from palatium_ai.domain.ports.mcp import MCPRegistryPort, McpToolCallRecorderPort

logger = get_logger(__name__)


async def run_llm_research(
    *,
    config: AgentConfig,
    harness: HarnessPort,
    tool_executor: ToolExecutor,
    mcp_registry: MCPRegistryPort | None,
    mcp_tool_call_repository: McpToolCallRecorderPort | None,
    task_input: ResearcherInput,
    context: AgentContext,
    skill_catalog: str,
    task_id: UUID,
    agent_role: str,
    grounding_degraded: bool = False,
    image_parts: tuple[ImagePart, ...] = (),
    document_parts: tuple[DocumentPart, ...] = (),
    project_agents_md: str = "",
) -> AgentOutput:
    sealed = _try_seal_attachment_fence(task_input, task_id=task_id, confidence_threshold=config.confidence_threshold)
    if sealed is not None:
        return sealed
    skill_references = await hydrate_skill_references(
        catalog_text=skill_catalog,
        user_text=task_input.context_packet.user_text,
        tool_executor=tool_executor,
        mcp_registry=mcp_registry,
        context=context,
        repository=mcp_tool_call_repository,
    )
    system = RESEARCHER_SYSTEM_PROMPT
    if grounding_degraded:
        system = f"{RESEARCHER_SYSTEM_PROMPT}\n{RESEARCHER_UNGROUNDED_SYSTEM_NOTE}"
    memory_block = "\n".join(f"- {hint}" for hint in task_input.memory_hints[:4] if str(hint).strip())
    dialog_block = ""
    if task_input.dialog_window is not None:
        # as_prompt_block applies DialogCorrectionPolicy (P1.1 supersede strip).
        dialog_block = task_input.dialog_window.as_prompt_block(max_chars=6_000)
        if dialog_block == "(no prior turns)":
            dialog_block = ""
    user_content = json.dumps(
        {
            "user_text": task_input.context_packet.user_text,
            "task_kind": task_input.context_packet.task_kind,
            "requires_mcp": task_input.context_packet.requires_mcp,
            "candidate_capabilities": task_input.context_packet.candidate_capabilities,
            "grounding": task_input.context_packet.grounding,
            "route_plan": task_input.context_packet.route_plan,
            "context_summary": task_input.context_packet.context_summary,
            "attached_files": task_input.context_packet.untrusted_context,
            "previous_answer": task_input.prior_context,
            "revision_feedback": task_input.revision_feedback,
            "skill_references": skill_references,
            "retrieval_empty": grounding_degraded,
        },
        ensure_ascii=False,
    )
    # CMD2 tiers: memory + skill index in context; ask/attachments in volatile user turn.
    assembled = PromptAssemblyPolicy.assemble(
        PromptAssemblyParts(
            system_identity=system,
            project_agents_md=project_agents_md,
            skill_catalog=skill_catalog,
            memory_block=memory_block,
            dialog_block=dialog_block,
            thread_meta=f"thread_id={context.thread_id}",
            user_content=user_content,
            image_parts=image_parts,
            document_parts=document_parts,
        )
    )
    messages = list(assembled.messages)

    llm_config = researcher_llm_config(
        config,
        strategy=task_input.context_packet.execution_plan.strategy,
        composer_mode=task_input.context_packet.composer_mode,
    )
    try:
        completion = await harness.call_llm(
            llm_config,
            messages,
            response_format="json_object",
            max_tokens=researcher_completion_budget(task_input.context_packet.candidate_capabilities),
        )
        output = parse_researcher_output(completion.content)
    except Exception:
        logger.exception("researcher LLM stage failed", task_id=str(task_id))
        agent_metrics.record_error(agent_role, "llm_stage_failure")
        return failure_output(
            task_id,
            summary=None,
            error="LLM stage failed in researcher agent",
        )

    fence_excerpt = _fence_excerpt(task_input)
    if grounding_degraded:
        output = ResearcherOutput(
            summary=output.summary,
            confidence=output.confidence,
            sources_used=output.sources_used or ("llm_ungrounded",),
            grounding_satisfied=False,
            grounding_degraded=True,
            cannot_answer_without_source=False,
            evidence_excerpt=fence_excerpt,
        )
        # ``grounding`` is a validated Literal (never empty), so it is passed as-is.
        agent_metrics.record_grounding_degraded(task_input.context_packet.grounding)
    elif fence_excerpt:
        # Synthesis over the uploaded fence: quotes of requisites/PII inside it are
        # citations, not leaks — Critic gets the same body as an allowed source (020).
        output = output.model_copy(update={"evidence_excerpt": fence_excerpt})

    requires_review = output.confidence < config.confidence_threshold
    status: Literal["success", "failure", "partial"] = "partial" if requires_review else "success"
    if requires_review:
        agent_metrics.record_human_escalation("low_confidence_research")

    return AgentOutput(
        task_id=task_id,
        status=status,
        confidence=output.confidence,
        output=output,
    )


def _try_seal_attachment_fence(
    task_input: ResearcherInput,
    *,
    task_id: UUID,
    confidence_threshold: float,
) -> AgentOutput | None:
    """Deterministic OCR seal for this-turn fences (same SoT as MCP read_attachment).

    Capability ∩ response_shape — not phrase lists in the prompt (055). Analysis
    shapes never seal even when verbatim was mistagged.
    """
    if not FileReferencePolicy.seals_thread_file_body(
        candidate_capabilities=task_input.context_packet.candidate_capabilities,
        response_shape=task_input.context_packet.response_shape,
    ):
        return None
    fence = (task_input.context_packet.untrusted_context or "").strip()
    if not fence:
        return None
    # A truncated / empty-OCR fence is not a deliverable: the observation path must
    # re-read from storage instead of sealing a partial body (065).
    if ResearcherObservationPolicy.evidence_incomplete(fence):
        return None
    body = strip_page_markers(unwrap_read_attachment_text(fence)).strip()
    if not body:
        return None
    if len(body) > SUMMARY_MAX_CHARS:
        body = body[:SUMMARY_MAX_CHARS].rstrip() + "…"
    scored = score_mcp_tool_confidence(is_error=False, summary_chars=len(body))
    confidence = max(confidence_threshold, scored)
    output = ResearcherOutput(
        summary=body,
        confidence=confidence,
        sources_used=("attachment:fence",),
        grounding_satisfied=True,
        evidence_excerpt=body,
    )
    agent_metrics.record_grounding_satisfied()
    status: Literal["success", "failure", "partial"] = "partial" if confidence < confidence_threshold else "success"
    logger.info(
        "researcher.seal_attachment_fence",
        task_id=str(task_id),
        body_chars=len(body),
    )
    return AgentOutput(task_id=task_id, status=status, confidence=confidence, output=output)


def _fence_excerpt(task_input: ResearcherInput) -> str:
    """This turn's uploaded fence as evidence for constitution PII checks (020).

    Bounded by ``EVIDENCE_EXCERPT_MAX_CHARS`` so a long contract still counts as a
    legitimate source without unbounded state (065).
    """
    from palatium_ai.domain.agents.researcher import EVIDENCE_EXCERPT_MAX_CHARS

    fence = (task_input.context_packet.untrusted_context or "").strip()
    if not fence:
        return ""
    return fence[:EVIDENCE_EXCERPT_MAX_CHARS]
