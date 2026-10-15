"""ExecutionPlanner respects Adaptive Grounding when enabled."""

from __future__ import annotations

import pytest

from palatium_ai.application.services.execution_planner import ExecutionPlanner
from palatium_ai.domain.agents.context_weaver import ContextWeaverInput


def _input(**overrides: object) -> ContextWeaverInput:
    base: dict[str, object] = {
        "task_id": "t1",
        "user_text": "сравни облако и on-prem",
        "task_kind": "knowledge_request",
        "route": "researcher",
        "route_plan": "answer",
        "requires_mcp": False,
        "grounding": "optional",
    }
    base.update(overrides)
    return ContextWeaverInput(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio()
async def test_grounding_none_skips_search_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "true")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "100")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    try:
        bundle = await ExecutionPlanner(capability_index=None).build(_input(grounding="none"))
        assert bundle.selected_strategy == "reason_only"
        assert bundle.requires_tool_call is False
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio()
async def test_grounding_optional_retrieves_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "true")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "100")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    try:
        bundle = await ExecutionPlanner(capability_index=None).build(_input(grounding="optional"))
        assert bundle.selected_strategy == "retrieve_then_reason"
        assert bundle.steps[0].tool_name == "search_knowledge"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio()
async def test_grounding_required_retrieves_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "true")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "100")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    try:
        bundle = await ExecutionPlanner(capability_index=None).build(_input(grounding="required"))
        assert bundle.selected_strategy == "retrieve_then_reason"
        assert bundle.requires_tool_call is True
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio()
async def test_grounding_required_overrides_trusted_prior(monkeypatch: pytest.MonkeyPatch) -> None:
    """Log bug: required + trusted prior → reason_only skipped MCP and echoed wrong OCR."""
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "true")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "100")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    try:
        bundle = await ExecutionPlanner(capability_index=None).build(
            _input(
                user_text="дай полный текст из файла",
                grounding="required",
                grounding_reason="needs user file contents",
                requires_mcp=False,
                has_trusted_prior=True,
                has_attachment_context=False,
            ),
        )
        assert bundle.selected_strategy == "retrieve_then_reason"
        assert bundle.requires_tool_call is True
        assert bundle.steps[0].tool_name == "search_knowledge"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio()
async def test_grounding_required_keeps_explicit_attachment_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This-turn upload fence still grounds without search (explicit OCR is the source)."""
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "true")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "100")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    try:
        bundle = await ExecutionPlanner(capability_index=None).build(
            _input(
                user_text="дай полный текст из файла",
                grounding="required",
                has_attachment_context=True,
                has_trusted_prior=True,
            ),
        )
        assert bundle.selected_strategy == "reason_only"
        assert bundle.requires_tool_call is False
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio()
async def test_compose_still_reason_only_with_adaptive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "true")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "100")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    try:
        bundle = await ExecutionPlanner(capability_index=None).build(
            _input(grounding="optional", candidate_capabilities=("compose",)),
        )
        assert bundle.selected_strategy == "reason_only"
    finally:
        get_settings.cache_clear()
