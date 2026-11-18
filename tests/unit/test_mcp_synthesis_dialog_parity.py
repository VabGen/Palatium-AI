"""MCP synthesis must carry dialog + document parts like the LLM research path."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from palatium_ai.application.agents.researcher.mcp_path import _synthesis_messages
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.researcher import ResearcherInput
from palatium_ai.domain.llm.models import DocumentPart
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow


def test_synthesis_messages_include_dialog_and_document_parts() -> None:
    dialog = DialogTurnWindow(
        thread_id="t1",
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id="t1",
                role="user",
                content="Первый вопрос",
                seq=0,
                created_at=datetime.now(UTC),
            ),
            DialogTurn(
                id=uuid4(),
                thread_id="t1",
                role="assistant",
                content="Предыдущий ответ ассистента",
                seq=1,
                created_at=datetime.now(UTC),
            ),
        ),
        limit=12,
    )
    packet = ContextPacket(
        task_id="task-1",
        user_text="А предыдущий ответ?",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="answer from dialog",
        requires_mcp=True,
        execution_plan=ToolExecutionPlan(
            strategy="direct_tool_call",
            capability="attachments",
            server_name="platform",
            tool_name="search_knowledge",
            requires_tool_call=True,
            rationale="test",
        ),
        context_summary="dialog follow-up",
        untrusted_context="",
    )
    task_input = ResearcherInput(
        task_id="task-1",
        context_packet=packet,
        prior_context="Предыдущий ответ ассистента",
        dialog_window=dialog,
        memory_hints=("user prefers RU",),
    )
    doc = DocumentPart(attachment_id=uuid4(), title="note.pdf", text="body of note")
    messages = _synthesis_messages(
        task_input,
        tool_result="mcp hits…",
        source="mcp:platform.search_knowledge",
        document_parts=(doc,),
    )
    assert messages
    user = messages[-1]
    assert (
        "Предыдущий ответ" in (user.content or "")
        or any(
            "Предыдущий ответ" in (getattr(block, "text", "") or "")
            for block in (user.content if isinstance(user.content, list) else [])
        )
        or "Предыдущий ответ" in str(messages)
    )
    assembled_blob = "\n".join(str(m.content) for m in messages)
    assert "Предыдущий ответ" in assembled_blob
    assert "mcp hits" in assembled_blob
    assert user.document_parts == (doc,)


def test_clear_attached_files_drops_fence_and_parts() -> None:
    packet = ContextPacket(
        task_id="task-2",
        user_text="перечитай",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="reread",
        requires_mcp=True,
        execution_plan=ToolExecutionPlan(
            strategy="direct_tool_call",
            capability="attachments",
            server_name="platform",
            tool_name="read_attachment",
            requires_tool_call=True,
            rationale="test",
        ),
        context_summary="reread",
        untrusted_context="… [attachment body truncated] … OLD FENCE …",
    )
    task_input = ResearcherInput(task_id="task-2", context_packet=packet)
    doc = DocumentPart(attachment_id=uuid4(), title="old.pdf", text="stale")
    messages = _synthesis_messages(
        task_input,
        tool_result="fresh body from storage",
        source="mcp:platform.read_attachment",
        document_parts=(doc,),
        clear_attached_files=True,
    )
    blob = "\n".join(str(m.content) for m in messages)
    assert "OLD FENCE" not in blob
    assert "fresh body from storage" in blob
    assert messages[-1].document_parts == ()
