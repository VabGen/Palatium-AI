"""Runner cassette resolution for MCP researcher eval tasks."""

from __future__ import annotations

import pytest

from palatium_ai.application.agents.evals.runner import _resolve_task_output


@pytest.mark.asyncio
async def test_resolve_task_output_runs_researcher_args_cassette_without_main_cassette() -> None:
    task = {
        "id": "researcher-search-knowledge",
        "args_cassette": "researcher/search_knowledge_args.json",
        "input": {
            "user_text": "Search knowledge index for Palatium architecture overview",
            "task_kind": "knowledge_request",
            "route": "researcher",
            "requires_mcp": True,
            "requires_tool_call": True,
            "selected_strategy": "direct_tool_call",
            "server_name": "platform",
            "tool_name": "search_knowledge",
        },
    }
    output, mode = await _resolve_task_output("researcher", task, {})
    assert mode == "cassette"
    assert output.get("used_mcp_source") is True
    assert output.get("mcp_tool") == "search_knowledge"
    assert output.get("summary")
