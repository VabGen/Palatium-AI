"""Soft-empty MCP maps to partial without requires_review."""

from uuid import uuid4

from palatium_ai.application.agents.researcher.outcomes import soft_empty_output
from palatium_ai.application.orchestration.agent_bridge import researcher_output_to_task_result
from palatium_ai.domain.agents.researcher import MCP_EMPTY_RESULT


def test_soft_empty_bridge_skips_review() -> None:
    output = soft_empty_output(uuid4(), error=MCP_EMPTY_RESULT)
    result = researcher_output_to_task_result(output, task_id="t1", agent_role="researcher")
    assert result.status == "partial"
    assert result.requires_review is False
    assert result.error == MCP_EMPTY_RESULT
    assert result.output is None
