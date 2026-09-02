# palatium_ai/core/exceptions.py

"""Исключения платформы (core-only; domain errors stay in domain)."""


class PalatiumError(Exception):
    """Базовое исключение платформы."""


class AuditChainIntegrityError(PalatiumError):
    """Audit log chain is corrupt or unreadable; refuse silent genesis reset."""


class ToolNotAllowedError(PalatiumError, PermissionError):
    """Вызов инструмента вне RBAC allow-list."""

    def __init__(self, tool_name: str, allowed_tools: tuple[str, ...]) -> None:
        self.tool_name = tool_name
        self.allowed_tools = allowed_tools
        super().__init__(
            f"Tool '{tool_name}' is not allowed. Allowed tools: {allowed_tools}",
        )


class AgentExecutionError(PalatiumError):
    """Ошибка выполнения агента после исчерпания retry."""


class ClarifyError(PalatiumError):
    """Ошибка при запросе дополнительной информации."""


class AuditWriteDegradedError(RuntimeError):
    """Audit write failed on I/O level; event preserved in dead-letter.

    Бизнес-флоу ОБЯЗАН ловить это исключение и продолжать работу —
    деградация аудита не должна превращаться в пользовательскую ошибку.
    """
