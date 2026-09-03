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
    max_quality_revisions: int = Field(
        default=2,
        ge=0,
        le=10,
        validation_alias="MAX_QUALITY_REVISIONS",
        description="HITL quality revise budget per thread (065 MAX_REVISIONS).",
    )
    circuit_failures_to_open: int = Field(
        default=3,
        ge=1,
        le=20,
        validation_alias="CIRCUIT_FAILURES_TO_OPEN",
    )
    circuit_open_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=3600.0,
        validation_alias="CIRCUIT_OPEN_SECONDS",
    )
