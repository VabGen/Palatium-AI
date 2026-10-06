"""Unit tests for L1 ResponseCacheKeyPolicy + in-memory cache service."""

from __future__ import annotations

from uuid import uuid4

import pytest

from palatium_ai.application.services.response_cache_service import ResponseCacheService
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.content.content_document import ContentDocument, DocumentMeta, ParagraphBlock
from palatium_ai.domain.policies.response_cache import ResponseCacheKeyParts, ResponseCacheKeyPolicy
from palatium_ai.infrastructure.cache.response_cache import InMemoryResponseCache


def test_normalize_collapses_whitespace() -> None:
    assert ResponseCacheKeyPolicy.normalize_user_text("  Привет\n\tмир  ") == "привет мир"


def test_format_key_stable() -> None:
    a = ResponseCacheKeyPolicy.build_key(
        ResponseCacheKeyParts(
            tenant_key="t1",
            model="strategy:format_only",
            system_fingerprint="format_only_v1",
            user_norm=ResponseCacheKeyPolicy.normalize_user_text("Hi!"),
            strategy="format_only",
            locale="en",
        )
    )
    b = ResponseCacheKeyPolicy.build_key(
        ResponseCacheKeyParts(
            tenant_key="t1",
            model="strategy:format_only",
            system_fingerprint="format_only_v1",
            user_norm=ResponseCacheKeyPolicy.normalize_user_text("  hi!  "),
            strategy="format_only",
            locale="en",
        )
    )
    assert a == b
    assert a.startswith("palatium:l1:")


def test_tenant_isolates_keys() -> None:
    a = ResponseCacheKeyPolicy.build_key(
        ResponseCacheKeyParts(
            tenant_key="a",
            model="strategy:format_only",
            system_fingerprint="format_only_v1",
            user_norm="hi",
            strategy="format_only",
            locale="en",
        )
    )
    b = ResponseCacheKeyPolicy.build_key(
        ResponseCacheKeyParts(
            tenant_key="b",
            model="strategy:format_only",
            system_fingerprint="format_only_v1",
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
        user_text="привет",
        locale="ru",
        strategy="format_only",
        result=result,
    )
    hit = await svc.get(
        tenant_key="tenant-1",
        user_text="Привет",
        locale="ru",
        strategy="format_only",
    )
    assert hit is not None
    assert hit.output is not None
    assert hit.output.title == "Hello!"


@pytest.mark.asyncio()
async def test_response_cache_skips_non_low_risk() -> None:
    port = InMemoryResponseCache()
    svc = ResponseCacheService(port, ttl_seconds=60, enabled=True)
    await svc.put_if_cacheable(
        tenant_key="tenant-1",
        user_text="explain RAG",
        locale="en",
        strategy="retrieve_then_reason",
        result=_sample_result(),
    )
    assert (
        await svc.get(
            tenant_key="tenant-1",
            user_text="explain RAG",
            locale="en",
            strategy="retrieve_then_reason",
        )
        is None
    )


@pytest.mark.asyncio()
async def test_ack_only_put_is_no_op() -> None:
    port = InMemoryResponseCache()
    svc = ResponseCacheService(port, ttl_seconds=60, enabled=True)
    await svc.put_if_cacheable(
        tenant_key="tenant-1",
        user_text="привет",
        locale="ru",
        strategy="ack_only",
        result=_sample_result(),
    )
    assert (
        await svc.get(
            tenant_key="tenant-1",
            user_text="привет",
            locale="ru",
            strategy="ack_only",
        )
        is None
    )
