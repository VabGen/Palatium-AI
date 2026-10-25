# src/palatium_ai/application/agents/researcher/llm_research.py

"""LLM research path (no MCP tool call) for ResearcherAgent."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from palatium_ai.application.agents.researcher.config import (
    researcher_completion_budget,
    researcher_llm_config,
)
from palatium_ai.application.agents.researcher.outcomes import failure_output
from palatium_ai.application.agents.researcher.parsing import parse_researcher_output
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
from palatium_ai.domain.llm.models import ChatMessage, ImagePart

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
) -> AgentOutput:
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
    messages = [
        ChatMessage(role="system", content=system),
        ChatMessage(
            role="user",
            content=json.dumps(
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
                    "user_facts": list(task_input.memory_hints[:4]),
                    "skill_catalog": skill_catalog,
                    "skill_references": skill_references,
                    "retrieval_empty": grounding_degraded,
                },
                ensure_ascii=False,
            ),
            # Images ride on the user turn (the ask), never on system/assistant turns;
            # the admission decision was made once at graph entry (ADR 0007).
            image_parts=image_parts,
        ),
    ]

    llm_config = researcher_llm_config(
        config,
        strategy=task_input.context_packet.execution_plan.strategy,
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

    if grounding_degraded:
        output = ResearcherOutput(
            summary=output.summary,
            confidence=output.confidence,
            sources_used=output.sources_used or ("llm_ungrounded",),
            grounding_satisfied=False,
            grounding_degraded=True,
            cannot_answer_without_source=False,
        )
        # ``grounding`` is a validated Literal (never empty), so it is passed as-is.
        agent_metrics.record_grounding_degraded(task_input.context_packet.grounding)

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
