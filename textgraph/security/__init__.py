"""Enterprise fine-grained access control (Phase 9, ``[security]`` extra for OpenFGA).

ReBAC (Zanzibar/OpenFGA-style relation tuples) + ABAC (Cedar-style attribute conditions)
enforced *inside* graph traversal: an unauthorized document's nodes get a zero transition
probability in Personalized PageRank, so they cannot leak through multi-hop retrieval,
paths, or community summaries (the gap analysis §3.2 "security-aware traversal", not a
post-filter). Pure-Python and deterministic by default; the artifact is untouched because
access control is purely a query-time concern — attach a :class:`SecurityPolicy` to a
``QueryEngine`` and pass a :class:`SecurityContext` per tool call.
"""

from textgraph.security.abac import AbacRule, IpAllowlist, MinClearance, TimeWindow
from textgraph.security.context import SecurityContext
from textgraph.security.policy import (
    SecurityPolicy,
    policy_from_dict,
    resolve_policy_engine,
)
from textgraph.security.rebac import RebacStore, RelationTuple

__all__ = [
    "AbacRule",
    "IpAllowlist",
    "MinClearance",
    "RebacStore",
    "RelationTuple",
    "SecurityContext",
    "SecurityPolicy",
    "TimeWindow",
    "policy_from_dict",
    "resolve_policy_engine",
]
