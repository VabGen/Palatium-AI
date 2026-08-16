# palatium_ai/core/types/uuid.py

from dataclasses import dataclass
from uuid import UUID, uuid7


@dataclass(frozen=True)
class UUIDv7:
    """Базовый неизменяемый идентификатор версии 7 (сортируется по времени)."""

    value: UUID

    @classmethod
    def generate(cls) -> UUIDv7:
        """Создать новый UUIDv7."""
        return cls(value=uuid7())

    @classmethod
    def from_str(cls, s: str) -> UUIDv7:
        """Создать идентификатор из строки (валидация формата)."""
        return cls(value=UUID(s))

    def __str__(self) -> str:
        """Возвращает строковое представление идентификатора."""
        return str(self.value)

    def __repr__(self) -> str:
        """Возвращает подробное отладочное представление."""
        return f"{self.__class__.__name__}({self.value!r})"
