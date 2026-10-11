"""SSE process_stream lifecycle: done after result; disconnect acloses generator."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from palatium_ai.presentation.api.routers import intents as intents_router


async def _fake_process_stream(**_kwargs: Any) -> AsyncIterator[dict[str, Any]]:
    yield {"event": "hop", "node": "researcher", "task_id": "t1", "thread_id": "th1"}
    yield {
        "event": "answer_delta",
        "delta": "OCR line one",
        "task_id": "t1",
        "thread_id": "th1",
    }
    yield {
        "event": "result",
        "task_id": "t1",
        "thread_id": "th1",
        "result": {"task_id": "t1", "status": "success"},
    }


@pytest.mark.asyncio()
async def test_process_stream_emits_done_after_result() -> None:
    app = FastAPI()
    app.include_router(intents_router.router, prefix="/intents")

    principal = MagicMock(subject="u1", org_id="o1")
    resources = MagicMock()
    resources.intent_service.process_stream = _fake_process_stream

    with (
        patch.object(intents_router, "get_principal", return_value=principal),
        patch.object(intents_router, "principal_is_admin", return_value=False),
        patch.object(intents_router, "get_app_resources", return_value=resources),
    ):
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://test") as client,
            client.stream(
                "POST",
                "/intents/process/stream",
                json={"text": "дай текст", "thread_id": "th1"},
            ) as response,
        ):
            assert response.status_code == 200
            body = ""
            async for chunk in response.aiter_text():
                body += chunk

    assert "event: answer_delta" in body
    assert "event: result" in body
    assert "event: done" in body
    assert body.rfind("event: done") > body.rfind("event: result")


@pytest.mark.asyncio()
async def test_process_stream_disconnect_aclose() -> None:
    closed = False

    async def _stream(**_kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        nonlocal closed
        try:
            yield {"event": "hop", "node": "intent", "task_id": "t1", "thread_id": "th1"}
            yield {"event": "hop", "node": "researcher", "task_id": "t1", "thread_id": "th1"}
        finally:
            closed = True

    app = FastAPI()
    app.include_router(intents_router.router, prefix="/intents")
    principal = MagicMock(subject="u1", org_id="o1")
    resources = MagicMock()
    resources.intent_service.process_stream = _stream

    request_mock = MagicMock()
    # First check after first event → disconnected; aclose path.
    request_mock.is_disconnected = AsyncMock(side_effect=[False, True, True])

    with (
        patch.object(intents_router, "get_principal", return_value=principal),
        patch.object(intents_router, "principal_is_admin", return_value=False),
        patch.object(intents_router, "get_app_resources", return_value=resources),
    ):
        # Call the route handler directly to control Request.is_disconnected.
        body = intents_router.ClassifyIntentRequest(text="hi", thread_id="th1")
        response = await intents_router.process_intent_stream(body, request_mock)
        chunks = [chunk if isinstance(chunk, str) else chunk.decode() async for chunk in response.body_iterator]

    joined = "".join(chunks)
    assert "event: hop" in joined
    assert "event: done" not in joined
    assert closed is True
