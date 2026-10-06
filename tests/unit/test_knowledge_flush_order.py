# tests/unit/test_knowledge_flush_order.py

"""Regression: ORM flush must insert ``knowledge.documents`` before ``knowledge.chunks``.

Без ``relationship()`` между мапперами unit-of-work SQLAlchemy сортирует их по имени
(``KnowledgeChunkORM`` < ``KnowledgeDocumentORM``) и отправляет INSERT для ``chunks``
первым, что даёт ``ForeignKeyViolationError`` на живой PostgreSQL (060).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from sqlalchemy import create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from palatium_ai.infrastructure.database.models.knowledge_chunk import (
    KnowledgeChunkORM,
    KnowledgeDocumentORM,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine
    from sqlalchemy.sql.base import Executable


def _recording_engine(statements: list[str]) -> Engine:
    """Собирает скомпилированный SQL до его выполнения (таблиц может и не быть)."""
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "before_execute")
    def _record(
        conn: Connection,
        clauseelement: Executable,
        multiparams: object,
        params: object,
        execution_options: object,
    ) -> None:
        statements.append(str(clauseelement))

    return engine


def test_document_insert_precedes_chunk_insert() -> None:
    statements: list[str] = []
    engine = _recording_engine(statements)
    now = datetime.now(UTC)
    document_id = uuid4()

    try:
        with Session(engine) as session:
            session.add(
                KnowledgeDocumentORM(
                    id=document_id,
                    user_id="flush-order-user",
                    thread_id="flush-order-thread",
                    title="Flush order",
                    chunk_count=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                KnowledgeChunkORM(
                    id=uuid4(),
                    document_id=document_id,
                    user_id="flush-order-user",
                    chunk_index=0,
                    text="chunk",
                    created_at=now,
                )
            )
            # SQLite без схемы ``knowledge`` падает на выполнении — важен только порядок.
            with pytest.raises(SQLAlchemyError):
                session.flush()
            session.rollback()
    finally:
        engine.dispose()

    inserts = [stmt for stmt in statements if stmt.lstrip().upper().startswith("INSERT")]
    assert inserts, f"flush не сгенерировал INSERT: {statements}"
    assert "knowledge.documents" in inserts[0], inserts


def test_chunk_mapper_declares_document_dependency() -> None:
    """Метаданные маппера содержат зависимость, на которой строится порядок flush."""
    relationships = KnowledgeChunkORM.__mapper__.relationships
    assert [rel.mapper.class_ for rel in relationships] == [KnowledgeDocumentORM]
