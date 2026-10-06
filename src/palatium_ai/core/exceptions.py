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


class DatabaseUnavailableError(PalatiumError):
    """Postgres stayed unreachable after the retry budget — availability, not a bug.

    Postgres answers "the database system is in recovery mode" (SQLSTATE 57P03) while
    it restarts, and drops pings/sockets while it drains. Those are expected
    operational failures (035), never an ASGI 500: the DB layer retries them briefly
    and, if the outage outlives the budget, raises this typed error so the API can
    answer ``503`` + ``Retry-After`` and the client knows the request never ran.
    """

    def __init__(self, *, operation: str, retry_after_seconds: int) -> None:
        self.operation = operation
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Database unavailable during {operation} after exhausting retries (retry in ~{retry_after_seconds}s)",
        )
