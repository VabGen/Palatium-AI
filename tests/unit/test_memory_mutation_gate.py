"""Chat memory mutation gate — read check → HITL card → write only after approve.

Covers E2E-01/03: an explicit «запомни …» / «забудь …» turn must never be answered
with a success claim, and nothing may reach ``memory.entries`` before approval.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.application.services.memory_forget_service import MEM_FORGET_TASK_PREFIX, MemoryForgetService
from palatium_ai.application.services.memory_mutation import MemoryMutationGate
from palatium_ai.application.services.memory_save_service import MEM_SAVE_TASK_PREFIX, MemorySaveService
from palatium_ai.domain.hitl.cards import HITLCardView
from palatium_ai.domain.memory.namespaces import user_namespace
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort
from tests.conftest import make_platform_mcp_registry

if TYPE_CHECKING:
    from palatium_ai.domain.agents.formatter import FormatterTaskResult

_USER = "user-1"
_THREAD = "thread-1"


@pytest.fixture()
def gate_stack() -> tuple[MemoryMutationGate, MemorySaveService, MemoryForgetService, InMemoryMemoryPort]:
    port = InMemoryMemoryPort()
    registry = make_platform_mcp_registry(memory_port=port)
    hitl = HitlService(InMemoryHitlCardStore(), signing_secret="unit-test-hitl-hmac-key-32bytes!!")
    save = MemorySaveService(hitl_service=hitl, mcp_registry=registry)
    forget = MemoryForgetService(hitl_service=hitl, mcp_registry=registry)
    gate = MemoryMutationGate(save_service=save, forget_service=forget, memory_port=port)
    return gate, save, forget, port


async def _seed(port: InMemoryMemoryPort, *, key: str, text: str) -> None:
    await port.put(
        namespace=user_namespace(_USER),
        key=key,
        value={"text": text, "user_id": _USER, "confidence": 1.0},
    )


def _cards(result: FormatterTaskResult) -> tuple[HITLCardView, ...]:
    return result.hitl_cards


@pytest.mark.asyncio()
async def test_save_stages_card_and_writes_only_after_approval(
    gate_stack: tuple[MemoryMutationGate, MemorySaveService, MemoryForgetService, InMemoryMemoryPort],
) -> None:
    gate, _save, _forget, port = gate_stack
    result = await gate.handle(
        task_id="task-save",
        thread_id=_THREAD,
        user_id=_USER,
        org_id="org-1",
        kind="save",
        text="порт базы 5433",
        key="db_port",
        locale="ru",
    )

    assert result.status == "partial"
    assert result.requires_review is True
    assert len(_cards(result)) == 1
    card = _cards(result)[0]
    assert card.task_id.startswith(MEM_SAVE_TASK_PREFIX)
    assert result.output is not None
    assert "порт базы 5433" in result.output.plain_text()
    # No write before human approval.
    assert await port.get(namespace=user_namespace(_USER), key="db_port") is None


@pytest.mark.asyncio()
async def test_save_supersedes_existing_subject_key(
    gate_stack: tuple[MemoryMutationGate, MemorySaveService, MemoryForgetService, InMemoryMemoryPort],
) -> None:
    gate, save, _forget, port = gate_stack
    await _seed(port, key="db_port", text="порт базы данных 5432")

    result = await gate.handle(
        task_id="task-save-2",
        thread_id=_THREAD,
        user_id=_USER,
        org_id="org-1",
        kind="save",
        text="порт базы данных 5433",
        key="",
        locale="ru",
    )
    card = _cards(result)[0]
    assert card.task_id.startswith(MEM_SAVE_TASK_PREFIX)

    await save.execute_after_approval(task_id=card.task_id)

    stored = await port.get(namespace=user_namespace(_USER), key="db_port")
    assert stored is not None
    assert stored["text"] == "порт базы данных 5433"
    hits = await port.search(namespace=user_namespace(_USER), query="порт", limit=8)
    assert len(hits) == 1, "a corrected fact must update the subject entry, not add a second one"


@pytest.mark.asyncio()
async def test_forget_resolves_stored_entry_and_deletes_after_approval(
    gate_stack: tuple[MemoryMutationGate, MemorySaveService, MemoryForgetService, InMemoryMemoryPort],
) -> None:
    gate, _save, forget, port = gate_stack
    await _seed(port, key="db_port", text="порт базы данных 5432")

    result = await gate.handle(
        task_id="task-forget",
        thread_id=_THREAD,
        user_id=_USER,
        org_id="org-1",
        kind="forget",
        text="порт базы",
        key="",
        locale="ru",
    )
    card = _cards(result)[0]
    assert card.task_id.startswith(MEM_FORGET_TASK_PREFIX)
    assert result.output is not None
    assert "порт базы данных 5432" in result.output.plain_text()
    assert await port.get(namespace=user_namespace(_USER), key="db_port") is not None

    await forget.execute_after_approval(task_id=card.task_id)
    assert await port.get(namespace=user_namespace(_USER), key="db_port") is None


@pytest.mark.asyncio()
async def test_forget_without_match_is_honest_and_mints_no_card(
    gate_stack: tuple[MemoryMutationGate, MemorySaveService, MemoryForgetService, InMemoryMemoryPort],
) -> None:
    gate, _save, _forget, _port = gate_stack
    result = await gate.handle(
        task_id="task-forget-missing",
        thread_id=_THREAD,
        user_id=_USER,
        org_id="org-1",
        kind="forget",
        text="лунный грунт",
        key="",
        locale="ru",
    )

    assert result.hitl_cards == ()
    assert result.status == "success"
    assert result.output is not None
    assert "ничего не нашлось" in result.output.plain_text().lower()


@pytest.mark.asyncio()
async def test_mutation_without_payload_never_claims_success(
    gate_stack: tuple[MemoryMutationGate, MemorySaveService, MemoryForgetService, InMemoryMemoryPort],
) -> None:
    gate, _save, _forget, _port = gate_stack
    result = await gate.handle(
        task_id="task-empty",
        thread_id=_THREAD,
        user_id=_USER,
        org_id="org-1",
        kind="save",
        text="   ",
        key="",
        locale="ru",
    )

    assert result.status == "failure"
    assert result.hitl_cards == ()
    assert result.error == "memory_mutation_unparsed"


@pytest.mark.asyncio()
async def test_mutation_without_owner_is_refused(
    gate_stack: tuple[MemoryMutationGate, MemorySaveService, MemoryForgetService, InMemoryMemoryPort],
) -> None:
    gate, _save, _forget, _port = gate_stack
    result = await gate.handle(
        task_id="task-no-owner",
        thread_id=_THREAD,
        user_id="",
        org_id="org-1",
        kind="save",
        text="порт 5433",
        key="db_port",
        locale="ru",
    )

    assert result.status == "failure"
    assert result.hitl_cards == ()
    assert result.error == "memory_mutation_unavailable"
