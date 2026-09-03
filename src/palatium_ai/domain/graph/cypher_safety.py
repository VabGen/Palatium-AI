# src/palatium_ai/domain/graph/cypher_safety.py

"""Read-only Cypher guards for ``graph_query`` (070 / 020)."""

from __future__ import annotations

import re

# Write / admin clauses forbidden on the read tool path (020: Neo4j mutations need HITL).
_FORBIDDEN_CLAUSE = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV|CALL\s+dbms|"
    r"CALL\s+db\.|FOREACH|APOC\.|PERIODIC\s+COMMIT)\b",
    re.IGNORECASE,
)
# Dynamic values must use $param placeholders, not string concat in the query text.
_STRING_INTERPOLATION = re.compile(r"(\{|%s|%\(|f['\"]|\"\s*\+|\+\s*[\"'])")
_PARAM_REF = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


def assert_read_only_cypher(cypher: str) -> None:
    """Raise ValueError when Cypher is not a parameterized read query."""
    cleaned = cypher.strip()
    if not cleaned:
        msg = "cypher must be non-empty"
        raise ValueError(msg)
    if _FORBIDDEN_CLAUSE.search(cleaned):
        msg = "graph_query allows read-only Cypher (MATCH/RETURN/...); write clauses require HITL write tools"
        raise ValueError(msg)
    if _STRING_INTERPOLATION.search(cleaned):
        msg = "Cypher must not use string interpolation; bind values via $params only"
        raise ValueError(msg)
    if not re.search(r"\b(MATCH|RETURN|WITH|UNWIND|CALL)\b", cleaned, re.IGNORECASE):
        msg = "Cypher must include a read clause (MATCH/RETURN/WITH/UNWIND/CALL)"
        raise ValueError(msg)


def referenced_param_names(cypher: str) -> frozenset[str]:
    """Return ``$param`` names referenced in the query."""
    return frozenset(_PARAM_REF.findall(cypher))


def assert_params_cover_refs(cypher: str, params: dict[str, object]) -> None:
    """Every ``$param`` in Cypher must exist in the params object."""
    missing = sorted(referenced_param_names(cypher) - frozenset(params))
    if missing:
        msg = f"missing Cypher params: {', '.join(missing)}"
        raise ValueError(msg)
