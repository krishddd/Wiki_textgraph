"""L-standards — a GQL (ISO/IEC 39075) query surface over the graph (Phase 7).

A pure-Python, deterministic subset of GQL/Cypher — property-graph pattern matching
with quantified (variable-length) relationships, WHERE/RETURN/ORDER BY/LIMIT — that
runs against the same ``(nodes, edges)`` the L8 tools use. Standardising the query
surface lets enterprise agents query TextGraph the same way they query any GQL backend
(Neo4j, Memgraph, Kùzu). Read-only; G1/G2/G3 untouched. See :mod:`textgraph.gql.engine`.
"""

from textgraph.gql.engine import GQLEngine, QueryResult
from textgraph.gql.errors import GQLError
from textgraph.gql.parser import parse

__all__ = ["GQLEngine", "GQLError", "QueryResult", "parse"]
