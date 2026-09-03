# src/palatium_ai/core/observability/span_names.py

"""Единый реестр имён span'ов (040) — не строковые литералы по коду."""

from __future__ import annotations

HTTP_REQUEST = "http.request"

# Agents
AGENT_LLM_CALL = "agent.llm_call"
HARNESS_EXECUTE = "harness.execute_with_guardrails"

# Graph nodes (LangGraph topology + checkpoint migration)
NODE_CONTEXT_ENRICHER_CONTINUATION = "graph.node.context_enricher.continuation"
NODE_CONTEXT_ENRICHER_WEAVING = "graph.node.context_enricher.weaving"
NODE_INTENT = "graph.node.intent_classifier"
NODE_SUPERVISOR = "graph.node.supervisor"
NODE_RESEARCHER = "graph.node.researcher"
NODE_CODER = "graph.node.coder"
NODE_ANALYST = "graph.node.analyst"
NODE_CRITIC = "graph.node.critic"
NODE_QUALITY_REVISION = "graph.node.quality_revision"
NODE_FORMATTER = "graph.node.formatter"
# Legacy span aliases (pre context_enricher rename)
NODE_CONTEXTUALIZER = NODE_CONTEXT_ENRICHER_CONTINUATION
NODE_CONTEXT_WEAVER = NODE_CONTEXT_ENRICHER_WEAVING

# Tools
TOOL_EXECUTOR_TRY = "tool_executor.try_execute"
TOOL_EXECUTOR_EXECUTE = "tool_executor.execute"
