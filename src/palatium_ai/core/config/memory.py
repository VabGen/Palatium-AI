# src/palatium_ai/core/config/memory.py

"""Настройки памяти / checkpointer."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator

from .base import BaseConfig


class MemoryConfig(BaseConfig):
    """Memory spine toggles (recall gate + optional durable checkpointer)."""

    backend: Literal["postgres", "mem0", "graphiti"] = Field(
        default="postgres",
        validation_alias="MEMORY_BACKEND",
    )
    recall_min_confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        validation_alias="MEMORY_RECALL_MIN_CONFIDENCE",
    )
    recall_max_items: int = Field(
        default=4,
        ge=1,
        le=8,
        validation_alias="MEMORY_RECALL_MAX_ITEMS",
    )
    recall_max_chars: int = Field(
        default=800,
        ge=100,
        le=4000,
        validation_alias="MEMORY_RECALL_MAX_CHARS",
    )
    contextualizer_dialog_max_chars: int = Field(
        default=12_000,
        ge=500,
        le=32_000,
        validation_alias="CONTEXTUALIZER_DIALOG_MAX_CHARS",
    )
    worker_summary_max_chars: int = Field(
        default=8_000,
        ge=500,
        le=16_000,
        validation_alias="WORKER_SUMMARY_MAX_CHARS",
    )
    mcp_tool_output_max_chars: int = Field(
        default=3000,
        ge=500,
        le=16_000,
        validation_alias="MCP_TOOL_OUTPUT_MAX_CHARS",
    )
    use_postgres_checkpointer: bool = Field(
        default=False,
        validation_alias="LANGGRAPH_CHECKPOINT_POSTGRES",
    )
    embedding_rerank: bool = Field(
        default=False,
        validation_alias="MEMORY_EMBEDDING_RERANK",
    )
    mem0_api_key: SecretStr | None = Field(default=None, validation_alias="MEM0_API_KEY")
    mem0_host: str = Field(default="https://api.mem0.ai", validation_alias="MEM0_HOST")
    mem0_timeout_seconds: float = Field(
        default=30.0,
        ge=5.0,
        le=120.0,
        validation_alias="MEM0_TIMEOUT_SECONDS",
    )
    graphiti_neo4j_uri: str = Field(
        default="bolt://localhost:7687",
        validation_alias="GRAPHITI_NEO4J_URI",
    )
    graphiti_neo4j_user: str = Field(default="neo4j", validation_alias="GRAPHITI_NEO4J_USER")
    graphiti_neo4j_password: SecretStr | None = Field(
        default=None,
        validation_alias="GRAPHITI_NEO4J_PASSWORD",
    )

    @field_validator("mem0_api_key", "graphiti_neo4j_password", mode="before")
    @classmethod
    def _empty_secret_as_none(cls, value: object) -> object:
        if value is None or value == "":
            return None
        return value
