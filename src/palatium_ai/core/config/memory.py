# src/palatium_ai/core/config/memory.py

"""Настройки памяти / checkpointer."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator

from palatium_ai.core.types.retrieval import DEFAULT_RRF_K, HybridFusion

from .base import BaseConfig


class MemoryConfig(BaseConfig):
    """Memory spine toggles (recall gate + optional durable checkpointer)."""

    backend: Literal["postgres", "mem0", "graphiti"] = Field(
        default="postgres",
        validation_alias="MEMORY_BACKEND",
    )
    hybrid_fusion: HybridFusion = Field(
        default="rrf",
        validation_alias="MEMORY_HYBRID_FUSION",
    )
    rrf_k: int = Field(
        default=DEFAULT_RRF_K,
        ge=1,
        le=200,
        validation_alias="MEMORY_RRF_K",
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
    session_ttl_seconds: int = Field(
        default=1800,
        ge=60,
        le=30 * 24 * 3600,
        validation_alias="MEMORY_SESSION_TTL_SECONDS",
        description="Hot inactivity window for short-term checkpoints (ADR 0003).",
    )
    # None → resolve from ENVIRONMENT (staging/production on; development off).
    use_postgres_checkpointer: bool | None = Field(
        default=None,
        validation_alias="LANGGRAPH_CHECKPOINT_POSTGRES",
    )
    embedding_rerank: bool = Field(
        default=False,
        validation_alias="MEMORY_EMBEDDING_RERANK",
    )
    # --- Wave M8: eval-gated advanced (OFF by default; enable only when evals justify) ---
    importance_half_life_days: float = Field(
        default=7.0,
        gt=0.0,
        le=3650.0,
        validation_alias="MEMORY_IMPORTANCE_HALF_LIFE_DAYS",
        description="τ-decay half-life for search-time recency (days).",
    )
    cross_encoder_rerank: bool = Field(
        default=False,
        validation_alias="MEMORY_CROSS_ENCODER_RERANK",
        description="Opt-in cross-encoder rerank after hybrid retrieval (needs CrossEncoderPort).",
    )
    binary_quantize_rerank: bool = Field(
        default=False,
        validation_alias="MEMORY_BINARY_QUANTIZE_RERANK",
        description="Opt-in bit(4096) Hamming prefilter before float cosine (060 ANN path).",
    )
    bayesian_trust: bool = Field(
        default=False,
        validation_alias="MEMORY_BAYESIAN_TRUST",
        description="Opt-in Beta-Bernoulli trust updates on promote refresh/supersede.",
    )
    xmemory_decouple: bool = Field(
        default=False,
        validation_alias="MEMORY_XMEMORY_DECOUPLE",
        description="Opt-in decouple-before-aggregate near-dup collapse in promote batch.",
    )
    hebbian_edge_bump: bool = Field(
        default=False,
        validation_alias="MEMORY_HEBBIAN_EDGE_BUMP",
        description="Opt-in Hebbian weight bump on SUPERSEDES edges during promote.",
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
    graph_query_backend: Literal["in_memory", "neo4j"] = Field(
        default="in_memory",
        validation_alias="GRAPH_QUERY_BACKEND",
    )
    promote_enabled: bool = Field(
        default=True,
        validation_alias="MEMORY_PROMOTE_ENABLED",
    )
    promote_min_access_frequency: int = Field(
        default=3,
        ge=1,
        le=10_000,
        validation_alias="MEMORY_PROMOTE_MIN_ACCESS_FREQUENCY",
    )
    promote_min_importance: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        validation_alias="MEMORY_PROMOTE_MIN_IMPORTANCE",
    )
    promote_batch_limit: int = Field(
        default=32,
        ge=1,
        le=128,
        validation_alias="MEMORY_PROMOTE_BATCH_LIMIT",
    )

    @field_validator("mem0_api_key", "graphiti_neo4j_password", mode="before")
    @classmethod
    def _empty_secret_as_none(cls, value: object) -> object:
        if value is None or value == "":
            return None
        return value
