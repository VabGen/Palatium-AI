# palatium_ai/domain/agents/agent_id.py

"""Модуль agent_id содержит класс AgentId, который наследуется от UUIDv7."""

from dataclasses import dataclass

from palatium_ai.core.types import UUIDv7


@dataclass(frozen=True, slots=True)
class AgentId(UUIDv7):
    """Идентификатор агента (наследует UUIDv7)."""

    pass
