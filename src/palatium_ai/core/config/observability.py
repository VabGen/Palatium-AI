# src/palatium_ai/core/config/observability.py

"""
Модуль observability содержит класс ObservabilityConfig.

Наследуется от BaseConfig и содержит настройки мониторинга и телеметрии.
"""

from pydantic import Field, SecretStr

from .base import BaseConfig


class ObservabilityConfig(BaseConfig):
    """Настройки мониторинга и телеметрии."""

    langchain_tracing_v2: bool = Field(default=True, validation_alias="LANGCHAIN_TRACING_V2")
    langchain_api_key: SecretStr | None = Field(default=None, validation_alias="LANGCHAIN_API_KEY")
    langchain_project: str = Field(default="palatium-ai-prod", validation_alias="LANGCHAIN_PROJECT")
    otel_endpoint: str | None = Field(default=None, validation_alias="OTEL_ENDPOINT")
    turn_hop_budget_ms: int = Field(
        default=15_000,
        ge=1000,
        le=120_000,
        validation_alias="TURN_HOP_BUDGET_MS",
    )
    turn_cost_budget_usd: float = Field(
        default=0.0,
        ge=0.0,
        validation_alias="TURN_COST_BUDGET_USD",
        description="Hard per-turn LLM USD cap (0 disables).",
    )
    daily_cost_budget_usd: float = Field(
        default=0.0,
        ge=0.0,
        validation_alias="DAILY_COST_BUDGET_USD",
        description="Hard per-tenant daily LLM USD cap (0 disables).",
    )
