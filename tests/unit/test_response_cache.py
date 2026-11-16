"""Unit tests for L1 ResponseCacheKeyPolicy + in-memory cache service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from palatium_ai.application.services.response_cache_service import ResponseCacheService
from palatium_ai.application.services.turn_response_cache import (
    TurnResponseCacheContext,
    try_cached_formatter_result,
    turn_response_cache,
)
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput, FormatterTaskResult
from palatium_ai.domain.content.content_document import ContentDocument, DocumentMeta, ParagraphBlock
from palatium_ai.domain.hitl.cards import HITLCardView, HITLOption
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.domain.policies.response_cache import ResponseCacheKeyParts, ResponseCacheKeyPolicy
from palatium_ai.domain.policies.types import ResponseShape
from palatium_ai.infrastructure.cache.response_cache import InMemoryResponseCache


def test_normalize_collapses_whitespace() -> None:
    assert ResponseCacheKeyPolicy.normalize_user_text("  Привет\n\tмир  ") == "привет мир"


def test_format_key_stable() -> None:
    a = ResponseCacheKeyPolicy.build_key(
        ResponseCacheKeyParts(
            tenant_key="t1",
            thread_key="thread-1",
            model="strategy:format_only",
            system_fingerprint=ResponseCacheKeyPolicy.system_fingerprint_for("format_only"),
            user_norm=ResponseCacheKeyPolicy.normalize_user_text("Hi!"),
            strategy="format_only",
            locale="en",
            source_fingerprint="none",
        )
    )
    b = ResponseCacheKeyPolicy.build_key(
        ResponseCacheKeyParts(
            tenant_key="t1",
            thread_key="thread-1",
            model="strategy:format_only",
            system_fingerprint=ResponseCacheKeyPolicy.system_fingerprint_for("format_only"),
            user_norm=ResponseCacheKeyPolicy.normalize_user_text("  hi!  "),
            strategy="format_only",
            locale="en",
            source_fingerprint="none",
        )
    )
    assert a == b
    assert a.startswith("palatium:l1:")


def test_source_fingerprint_isolates_keys() -> None:
    base = dict(
        tenant_key="t1",
        thread_key="thread-1",
        model="strategy:format_only",
        system_fingerprint=ResponseCacheKeyPolicy.system_fingerprint_for("format_only"),
        user_norm="reformat",
        strategy="format_only",
        locale="en",
    )
    a = ResponseCacheKeyPolicy.build_key(
        ResponseCacheKeyParts(**base, source_fingerprint=ResponseCacheKeyPolicy.fingerprint_source("A"))
    )
    b = ResponseCacheKeyPolicy.build_key(
        ResponseCacheKeyParts(**base, source_fingerprint=ResponseCacheKeyPolicy.fingerprint_source("B"))
    )
    assert a != b


def test_tenant_isolates_keys() -> None:
    a = ResponseCacheKeyPolicy.build_key(
        ResponseCacheKeyParts(
            tenant_key="a",
            thread_key="thread-1",
            model="strategy:format_only",
            system_fingerprint=ResponseCacheKeyPolicy.system_fingerprint_for("format_only"),
            user_norm="hi",
            strategy="format_only",
            locale="en",
        )
    )
    b = ResponseCacheKeyPolicy.build_key(
        ResponseCacheKeyParts(
            tenant_key="b",
            thread_key="thread-1",
            model="strategy:format_only",
            system_fingerprint=ResponseCacheKeyPolicy.system_fingerprint_for("format_only"),
            user_norm="hi",
            strategy="format_only",
            locale="en",
        )
    )
    assert a != b


def test_ack_only_not_cacheable() -> None:
    assert ResponseCacheKeyPolicy.is_cacheable_strategy("ack_only") is False
    assert ResponseCacheKeyPolicy.is_cacheable_strategy("format_only") is True


def _sample_result() -> FormatterTaskResult:
    doc = ContentDocument(
        schema_version=1,
        locale="en",
        title="Hello!",
        blocks=(ParagraphBlock(type="paragraph", text="Hello!"),),
        actions=(),
        meta=DocumentMeta(confidence=1.0, requires_review=False, source_refs=(), interaction="none"),
    )
    return FormatterTaskResult(
        task_id=str(uuid4()),
        agent_role="formatter",
        status="success",
        confidence=1.0,
        requires_review=False,
        output=doc,
    )


@pytest.mark.asyncio()
async def test_response_cache_roundtrip() -> None:
    port = InMemoryResponseCache()
    svc = ResponseCacheService(port, ttl_seconds=60, enabled=True)
    result = _sample_result()
    await svc.put_if_cacheable(
        tenant_key="tenant-1",
        thread_key="thread-1",
        user_text="привет",
        locale="ru",
        strategy="format_only",
        result=result,
        source_content="prior answer body",
        continuation_kind="new_topic",
    )
    hit = await svc.get(
        tenant_key="tenant-1",
        thread_key="thread-1",
        user_text="Привет",
        locale="ru",
        strategy="format_only",
        source_content="prior answer body",
    )
    assert hit is not None
    assert hit.output is not None
    assert hit.output.title == "Hello!"
    miss = await svc.get(
        tenant_key="tenant-1",
        thread_key="thread-1",
        user_text="Привет",
        locale="ru",
        strategy="format_only",
        source_content="different prior",
    )
    assert miss is None
    other_thread = await svc.get(
        tenant_key="tenant-1",
        thread_key="thread-2",
        user_text="Привет",
        locale="ru",
        strategy="format_only",
        source_content="prior answer body",
    )
    assert other_thread is None, "the same words in another thread must not replay this answer"


@pytest.mark.asyncio()
async def test_response_cache_skips_non_low_risk() -> None:
    port = InMemoryResponseCache()
    svc = ResponseCacheService(port, ttl_seconds=60, enabled=True)
    await svc.put_if_cacheable(
        tenant_key="tenant-1",
        thread_key="thread-1",
        user_text="explain RAG",
        locale="en",
        strategy="retrieve_then_reason",
        result=_sample_result(),
    )
    assert (
        await svc.get(
            tenant_key="tenant-1",
            thread_key="thread-1",
            user_text="explain RAG",
            locale="en",
            strategy="retrieve_then_reason",
        )
        is None
    )


def _formatter_input(response_shape: ResponseShape) -> FormatterInput:
    packet = ContextPacket(
        task_id="t1",
        user_text="сделай таблицей",
        task_kind="response_formatting",
        route="formatter",
        route_plan="format_only",
        requires_mcp=False,
        response_shape=response_shape,
        execution_plan=ToolExecutionPlan(
            strategy="format_only",
            requires_tool_call=False,
            rationale="test packet",
        ),
        context_summary="n/a",
    )
    return FormatterInput(
        task_id="t1",
        context_packet=packet,
        worker_summary="prior answer body",
        response_locale="ru",
    )


@pytest.mark.asyncio()
async def test_explicit_shape_bypasses_l1_cache() -> None:
    """A cached echo must not skip shape generation (ADR 0005)."""
    port = InMemoryResponseCache()
    svc = ResponseCacheService(port, ttl_seconds=60, enabled=True)
    await svc.put_if_cacheable(
        tenant_key="tenant-1",
        thread_key="thread-1",
        user_text="сделай таблицей",
        locale="ru",
        strategy="format_only",
        result=_sample_result(),
        source_content="prior answer body",
        continuation_kind="new_topic",
    )
    ctx = TurnResponseCacheContext(cache=svc, tenant_key="tenant-1", thread_key="thread-1", user_text="сделай таблицей")
    window = None
    with turn_response_cache(ctx):
        auto_hit = await try_cached_formatter_result(
            task_input=_formatter_input("auto"),
            selected_strategy="format_only",
            dialog_window=window,
            continuation_kind="new_topic",
            trust_prior_for_workers=False,
            has_turn_attachments=False,
        )
        shaped = await try_cached_formatter_result(
            task_input=_formatter_input("comparison_table"),
            selected_strategy="format_only",
            dialog_window=window,
            continuation_kind="new_topic",
            trust_prior_for_workers=False,
            has_turn_attachments=False,
        )
    assert auto_hit is not None
    assert shaped is None


@pytest.mark.asyncio()
async def test_turn_with_hitl_card_is_not_cached() -> None:
    """A card is one-shot: replaying it from L1 would show an unresolvable card."""
    port = InMemoryResponseCache()
    svc = ResponseCacheService(port, ttl_seconds=60, enabled=True)
    result = _sample_result().model_copy(
        update={
            "status": "partial",
            "requires_review": True,
            "hitl_cards": (
                HITLCardView(
                    card_id="card-1",
                    thread_id="thread-1",
                    task_id="task-1",
                    purpose="mcp_tool_approval",
                    title="Approve MCP tool: platform.save_memory",
                    body="pending",
                    options=(HITLOption(action_id="approve", label="Allow", kind="approve"),),
                    risk_score=0.5,
                    status="pending",
                    created_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(minutes=5),
                    owner_user_id="user-1",
                    org_id="org-1",
                ),
            ),
        }
    )
    await svc.put_if_cacheable(
        tenant_key="tenant-1",
        thread_key="thread-1",
        user_text="запомни порт 5433",
        locale="ru",
        strategy="format_only",
        result=result,
        continuation_kind="new_topic",
    )
    assert (
        await svc.get(
            tenant_key="tenant-1",
            thread_key="thread-1",
            user_text="запомни порт 5433",
            locale="ru",
            strategy="format_only",
        )
        is None
    )


@pytest.mark.asyncio()
async def test_ack_only_put_is_no_op() -> None:
    port = InMemoryResponseCache()
    svc = ResponseCacheService(port, ttl_seconds=60, enabled=True)
    await svc.put_if_cacheable(
        tenant_key="tenant-1",
        thread_key="thread-1",
        user_text="привет",
        locale="ru",
        strategy="ack_only",
        result=_sample_result(),
        continuation_kind="new_topic",
    )
    assert (
        await svc.get(
            tenant_key="tenant-1",
            thread_key="thread-1",
            user_text="привет",
            locale="ru",
            strategy="ack_only",
        )
        is None
    )


def _window(*contents: tuple[str, str]) -> DialogTurnWindow:
    turns = tuple(
        DialogTurn(thread_id="thread-1", role=role, content=content, task_id=f"task-{index}")
        for index, (role, content) in enumerate(contents)
    )
    return DialogTurnWindow(thread_id="thread-1", turns=turns)


@pytest.mark.asyncio()
async def test_prior_dependent_turn_neither_reads_nor_writes_l1() -> None:
    """State bleed: an ``answer``/``format`` turn is generated for this dialog state.

    Replaying it on a later turn is the "answers the previous question" bug, so the
    continuation must neither store its result nor be served from an earlier one.
    """
    port = InMemoryResponseCache()
    svc = ResponseCacheService(port, ttl_seconds=60, enabled=True)
    await svc.put_if_cacheable(
        tenant_key="tenant-1",
        thread_key="thread-1",
        user_text="как меня зовут?",
        locale="ru",
        strategy="format_only",
        result=_sample_result(),
        source_content="prior answer body",
        continuation_kind="format",
        trust_prior_for_workers=True,
    )
    ctx = TurnResponseCacheContext(cache=svc, tenant_key="tenant-1", thread_key="thread-1", user_text="как меня зовут?")
    with turn_response_cache(ctx):
        assert (
            await try_cached_formatter_result(
                task_input=_formatter_input("auto"),
                selected_strategy="format_only",
                dialog_window=_window(("assistant", "Заявление об увеличении исковых требований")),
                continuation_kind="format",
                trust_prior_for_workers=True,
                has_turn_attachments=False,
            )
            is None
        )
    assert (
        await svc.get(
            tenant_key="tenant-1",
            thread_key="thread-1",
            user_text="как меня зовут?",
            locale="ru",
            strategy="format_only",
            source_content="prior answer body",
            prior_fingerprint=ResponseCacheKeyPolicy.fingerprint_prior(
                _window(("assistant", "Заявление об увеличении исковых требований"))
            ),
        )
        is None
    )


@pytest.mark.asyncio()
async def test_upload_turn_is_not_cached() -> None:
    port = InMemoryResponseCache()
    svc = ResponseCacheService(port, ttl_seconds=60, enabled=True)
    await svc.put_if_cacheable(
        tenant_key="tenant-1",
        thread_key="thread-1",
        user_text="что в файле?",
        locale="ru",
        strategy="format_only",
        result=_sample_result(),
        continuation_kind="new_topic",
        has_turn_attachments=True,
    )
    assert (
        await svc.get(
            tenant_key="tenant-1",
            thread_key="thread-1",
            user_text="что в файле?",
            locale="ru",
            strategy="format_only",
        )
        is None
    )


def test_prior_fingerprint_tracks_the_last_answer() -> None:
    empty = ResponseCacheKeyPolicy.fingerprint_prior(_window())
    first = ResponseCacheKeyPolicy.fingerprint_prior(_window(("assistant", "Ответ А")))
    second = ResponseCacheKeyPolicy.fingerprint_prior(_window(("assistant", "Ответ Б")))
    assert empty == "none"
    assert first != "none"
    assert first != second


def test_is_turn_cacheable_fails_closed_without_continuity() -> None:
    assert (
        ResponseCacheKeyPolicy.is_turn_cacheable(
            strategy="format_only",
            continuation_kind=None,
            trust_prior_for_workers=False,
            has_turn_attachments=False,
        )
        is False
    )
    assert (
        ResponseCacheKeyPolicy.is_turn_cacheable(
            strategy="format_only",
            continuation_kind="new_topic",
            trust_prior_for_workers=False,
            has_turn_attachments=False,
        )
        is True
    )
