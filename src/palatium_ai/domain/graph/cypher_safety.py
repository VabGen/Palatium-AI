# src/palatium_ai/domain/graph/cypher_safety.py

"""Read-only Cypher guards for ``graph_query`` (070 / 020)."""

from __future__ import annotations

import re

from palatium_ai.domain.graph.temporal import ACTIVE_FACT_AS_OF_PREDICATE, AS_OF_PARAM

# Tenant-scope placeholder forced into every ``graph_query`` (070: per-user graph reads).
TENANT_SCOPE_PARAM = "user_id"

# Write / admin clauses forbidden on the read tool path (020: Neo4j mutations need HITL).
# ``gds``/``apoc`` procedure namespaces can mutate; a READ_ACCESS session (infrastructure)
# is the structural backstop.
_FORBIDDEN_CLAUSE = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV|CALL\s+dbms|"
    r"CALL\s+db\.|CALL\s+gds|CALL\s+apoc|FOREACH|APOC\.|PERIODIC\s+COMMIT)\b",
    re.IGNORECASE,
)
# Dynamic values must use $param placeholders, not string formatting/concat in the query text.
_PY_FORMAT = re.compile(r"%s|%\(|f['\"]")
_CONCAT = re.compile(r"[\"']\s*\+|\+\s*[\"']")
_PARAM_REF = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
# A ``key: $param`` map entry — the only brace content a parameterized query needs.
_MAP_ENTRY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\s*:\s*\$[A-Za-z_][A-Za-z0-9_]*")
_BRACE_GROUP = re.compile(r"\{([^{}]*)\}")
# ``:MemoryFact`` — label is case-sensitive; ``\b`` keeps ``:MemoryFactActive`` (future label) out.
_FACT_LABEL = re.compile(r":\s*MemoryFact\b")
# ``(alias:MemoryFact)`` — the alias is what the temporal predicate must be written against.
_FACT_ALIAS = re.compile(r"\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*MemoryFact\b")
# One conjunct of the bi-temporal predicate per fact property: ``alias.prop IS NULL OR
# alias.prop <op> datetime($as_of)``. The null guard is part of the contract because
# ``NULL <= x`` is NULL, so dropping it silently hides facts whose validity is open-ended.
_TEMPORAL_CONJUNCTS: tuple[tuple[str, str], ...] = (
    ("valid_at", "<="),
    ("invalid_at", ">"),
    ("expired_at", ">"),
)


def _has_unbound_brace(cypher: str) -> bool:
    """True when a ``{...}`` group embeds a value instead of binding ``$param``.

    Braces themselves are legal Cypher (``MATCH (f:Fact {user_id: $user_id})`` is the
    canonical pattern), so they must not be banned wholesale. What *is* rejected is an
    f-string placeholder (``{user_id}``) or an inlined literal (``{kind: 'fact'}``):
    both mean the value travelled in the query text instead of being bound.
    """
    for body in _BRACE_GROUP.findall(cypher):
        stripped = body.strip()
        if not stripped:
            continue  # ``{}`` — legal empty property map
        remainder = _MAP_ENTRY.sub("", stripped).replace(",", "").strip()
        if remainder:
            return True
    return False


def assert_read_only_cypher(cypher: str) -> None:
    """Raise ValueError when Cypher is not a parameterized read query."""
    cleaned = cypher.strip()
    if not cleaned:
        msg = "cypher must be non-empty"
        raise ValueError(msg)
    if _FORBIDDEN_CLAUSE.search(cleaned):
        msg = "graph_query allows read-only Cypher (MATCH/RETURN/...); write clauses require HITL write tools"
        raise ValueError(msg)
    if _PY_FORMAT.search(cleaned) or _CONCAT.search(cleaned) or _has_unbound_brace(cleaned):
        msg = "Cypher must not use string interpolation; bind values via $params only"
        raise ValueError(msg)
    if not re.search(r"\b(MATCH|RETURN|WITH|UNWIND|CALL)\b", cleaned, re.IGNORECASE):
        msg = "Cypher must include a read clause (MATCH/RETURN/WITH/UNWIND/CALL)"
        raise ValueError(msg)


def referenced_param_names(cypher: str) -> frozenset[str]:
    """Return ``$param`` names referenced in the query."""
    return frozenset(_PARAM_REF.findall(cypher))


def assert_tenant_scoped_cypher(cypher: str, *, tenant_param: str = TENANT_SCOPE_PARAM) -> None:
    """Raise ValueError unless the read query references the tenant-scope placeholder.

    070/020: ``graph_query`` must not read across tenants. Placeholder reference is combined
    with forced ``$user_id`` injection and a READ_ACCESS session, so an unscoped
    ``MATCH (n) RETURN n`` can no longer return foreign-tenant rows.
    """
    if tenant_param not in referenced_param_names(cypher):
        msg = (
            f"graph_query must scope rows to the current tenant via ${tenant_param} "
            f"(e.g. MATCH (n {{user_id: ${tenant_param}}}) RETURN n)"
        )
        raise ValueError(msg)


def assert_params_cover_refs(cypher: str, params: dict[str, object]) -> None:
    """Every ``$param`` in Cypher must exist in the params object."""
    missing = sorted(referenced_param_names(cypher) - frozenset(params))
    if missing:
        msg = f"missing Cypher params: {', '.join(missing)}"
        raise ValueError(msg)


def _missing_temporal_conjuncts(alias: str, cypher: str) -> list[str]:
    """Conjuncts of ``ACTIVE_FACT_AS_OF_PREDICATE`` that ``alias`` is missing (F1b).

    Matching is semantic rather than byte-for-byte: property, comparison operator and
    ``datetime($as_of)`` are required, whitespace and case are not. Anything stricter
    would reject a correctly filtered query that was merely formatted differently;
    anything looser (e.g. "the string ``$as_of`` appears") accepts a query that binds a
    parameter and never filters on it — the exact gap the audit found.
    """
    escaped = re.escape(alias)
    as_of = rf"datetime\(\s*\$\s*{re.escape(AS_OF_PARAM)}\s*\)"
    missing: list[str] = []
    for prop, operator in _TEMPORAL_CONJUNCTS:
        conjunct = re.compile(
            rf"{escaped}\.{prop}\s+IS\s+NULL\s+OR\s+\(?\s*{escaped}\.{prop}\s*{re.escape(operator)}\s*{as_of}",
            re.IGNORECASE,
        )
        if not conjunct.search(cypher):
            missing.append(f"{alias}.{prop} {operator} datetime(${AS_OF_PARAM})")
    return missing


def assert_fact_read_is_temporal(cypher: str) -> None:
    """Refuse ``:MemoryFact`` reads that do not filter on the bi-temporal predicate.

    Without this the tool is fail-open: an agent writing ``MATCH (f:MemoryFact) ... RETURN``
    receives superseded and expired facts, so ``forget_memory`` stops being forgetting for
    any read path that did not copy the predicate by hand (M5 audit F1).

    F1b: binding ``$as_of`` is not enough — ``WHERE $as_of IS NOT NULL`` references the
    parameter and filters nothing. Every alias bound to ``:MemoryFact`` must carry all
    three conjuncts (valid-time ∩ system-time), so the only accepted shapes are the ones
    that cannot leak. A query that *deliberately* reads superseded facts is therefore not
    expressible through this tool: history inspection belongs to promote/inspection jobs,
    not to the agent's read path.
    """
    cleaned = cypher.replace("`", "")
    if not _FACT_LABEL.search(cleaned):
        return
    aliases = tuple(dict.fromkeys(_FACT_ALIAS.findall(cleaned)))
    if not aliases:
        msg = (
            "graph_query over :MemoryFact must bind the node to an alias "
            "(e.g. `MATCH (f:MemoryFact) WHERE ...`) so the bi-temporal predicate can be enforced"
        )
        raise ValueError(msg)
    missing = [conjunct for alias in aliases for conjunct in _missing_temporal_conjuncts(alias, cleaned)]
    if not missing:
        return
    msg = (
        "graph_query over :MemoryFact must carry the full bi-temporal predicate for every fact alias "
        f"(valid-time ∩ system-time); missing: {', '.join(missing)}. Build the WHERE clause as "
        f"`{ACTIVE_FACT_AS_OF_PREDICATE}` (substitute your alias for `f`) — otherwise superseded/expired "
        "facts leak into the answer"
    )
    raise ValueError(msg)


def assert_graph_query_safe(cypher: str, params: dict[str, object]) -> None:
    """Single choke point for the ``graph_query`` read path (070): read-only + tenant scope + params."""
    assert_read_only_cypher(cypher)
    assert_tenant_scoped_cypher(cypher)
    assert_params_cover_refs(cypher, params)
    assert_fact_read_is_temporal(cypher)
