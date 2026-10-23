# src/palatium_ai/domain/graph/temporal.py

"""Bi-temporal predicates for MemoryFact (Wave M5 / ADR 0004).

Valid-time: ``valid_at`` .. ``invalid_at`` (what was true in the world).
System-time: ``created_at`` .. ``expired_at`` (what the system still retains).
"""

from __future__ import annotations

from datetime import UTC, datetime

# Far-future system-time sentinel: Neo4j omits null props, so writes/indexes need a
# concrete ``expired_at`` to avoid UnknownPropertyKeyWarning (Phase 4).
EXPIRED_AT_SENTINEL = "9999-12-31T23:59:59Z"

# Parameter name every bi-temporal ``MemoryFact`` read must bind (see ``assert_fact_read_is_temporal``).
AS_OF_PARAM = "as_of"

# Parameterized Cypher fragment for ``graph_query`` (caller binds $as_of + $user_id).
# ``datetime($as_of)`` — Neo4j stores bi-temporal props as DateTime; raw string compare
# silently yields no rows (Wave M5 live verify 2026-10-06).
ACTIVE_FACT_AS_OF_PREDICATE = (
    "f.user_id = $user_id "
    "AND (f.valid_at IS NULL OR f.valid_at <= datetime($as_of)) "
    "AND (f.invalid_at IS NULL OR f.invalid_at > datetime($as_of)) "
    "AND (f.expired_at IS NULL OR f.expired_at > datetime($as_of))"
)


def is_fact_active_as_of(
    *,
    valid_at: datetime | None,
    invalid_at: datetime | None,
    expired_at: datetime | None,
    as_of: datetime,
) -> bool:
    """True when a fact is visible at ``as_of`` (valid-time ∩ system-time)."""
    moment = _aware(as_of)
    if valid_at is not None and _aware(valid_at) > moment:
        return False
    if invalid_at is not None and _aware(invalid_at) <= moment:
        return False
    return expired_at is None or _aware(expired_at) > moment


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


def as_of_param_value(as_of: datetime | None) -> str:
    """Bind value for ``$as_of``: requested moment or now, always UTC ``Z`` ISO-8601.

    ``datetime($as_of)`` in Cypher parses ISO-8601; the ``Z`` suffix avoids the
    ``+00:00``/offset handling differences between Neo4j versions.
    """
    moment = datetime.now(UTC) if as_of is None else _aware(as_of)
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
