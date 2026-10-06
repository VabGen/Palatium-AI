# src/palatium_ai/core/types/pagination.py

"""Pagination bounds for list endpoints (080) — single source, not per-route magic.

A list response without an upper bound is an unbounded query: one client can ask for
everything and the database happily complies. The bound is therefore a *policy* value,
declared once here and reused by every route (010: no magic numbers; 050: unwieldy
in-memory result sets and N+1 queries are anti-patterns).
"""

from __future__ import annotations

# Default page size: what a UI list wants, small enough to stay a single fast query.
PAGE_LIMIT_DEFAULT = 50
# Hard ceiling: the largest page a client may request. Raising this is a capacity
# decision — it must be a deliberate diff here, not an edited literal in a router.
PAGE_LIMIT_MAX = 200
