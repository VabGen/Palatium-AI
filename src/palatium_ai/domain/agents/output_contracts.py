# src/palatium_ai/domain/agents/output_contracts.py

"""Per-role AgentOutput.output schemas — harness fail-closed before verify (W8.4, ADR-0011)."""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel  # noqa: TC002 — runtime isinstance / ROLE_OUTPUT_TYPES values

from palatium_ai.core.types.w78_observability import SchemaMismatchReason
from palatium_ai.domain.agents.analyst import AnalystOutput
from palatium_ai.domain.agents.coder import CoderOutput
from palatium_ai.domain.agents.context_weaver import ContextWeaverOutput
from palatium_ai.domain.agents.critic import CriticOutput
from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.agents.memory_keeper import MemoryKeeperOutput
from palatium_ai.domain.agents.researcher import ResearcherOutput
from palatium_ai.domain.agents.supervisor import SupervisorOutput
from palatium_ai.domain.agents.text_ingestor import TextIngestorOutput
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.memory.contextualizer import ContextualizerOutput
from palatium_ai.domain.policies.types import AgentRole

#: Expected ``AgentOutput.output`` types per ``AgentConfig.role``.
#: ``context_enricher`` covers both continuation and weaving nodes (same role).
ROLE_OUTPUT_TYPES: Final[dict[AgentRole, tuple[type[BaseModel], ...]]] = {
    "intent_classifier": (IntentClassifierOutput,),
    "supervisor": (SupervisorOutput,),
    "researcher": (ResearcherOutput,),
    "critic": (CriticOutput,),
    "formatter": (ContentDocument,),
    "memory_keeper": (MemoryKeeperOutput,),
    "context_enricher": (ContextualizerOutput, ContextWeaverOutput),
    "text_ingestor": (TextIngestorOutput,),
    "coder": (CoderOutput,),
    "analyst": (AnalystOutput,),
}


def check_agent_output_schema(
    *,
    role: str,
    payload: BaseModel | None,
    status: str,
) -> SchemaMismatchReason | None:
    """Return mismatch reason, or ``None`` when the payload matches the role contract.

    Harness failure payloads (status=failure) skip the gate — they are not agent
    success paths. Schema check runs *before* ``agent.verify`` / LLM-judge (ADR-0009).
    """
    if status == "failure":
        return None
    if payload is None:
        return "missing_output"
    expected = ROLE_OUTPUT_TYPES.get(role)  # type: ignore[arg-type]
    if expected is None:
        return "unregistered_role"
    if isinstance(payload, expected):
        return None
    return "type_mismatch"


__all__ = [
    "ROLE_OUTPUT_TYPES",
    "check_agent_output_schema",
]
