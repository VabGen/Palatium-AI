# palatium_ai/core/exceptions.py

"""Исключения платформы."""


class PalatiumError(Exception):
    """Базовое исключение платформы."""


class SessionOwnershipError(PalatiumError, PermissionError):
    """Caller is not the session owner (and is not admin)."""


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
