"""In-memory GraphStore backend (Phase 1).

Deterministic iteration order (sorted by stable key) so artifacts built from a
store are byte-stable (G1). The DuckDB/Parquet backing store lands in Phase 4; call
sites depend only on the :class:`GraphStore` interface, so the swap is transparent.
"""

from __future__ import annotations

from textgraph.store.base import Edge, GraphStore, Node


class InMemoryGraphStore(GraphStore):
    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}
        self._out: dict[str, list[str]] = {}

    def add_node(self, node: Node) -> None:
        self._nodes[node.node_id] = node

    def add_edge(self, edge: Edge) -> None:
        self._edges[edge.edge_id] = edge
        self._out.setdefault(edge.subject, []).append(edge.edge_id)

    def get_node(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def neighbors(self, node_id: str) -> list[Edge]:
        edge_ids = self._out.get(node_id, [])
        return sorted((self._edges[e] for e in edge_ids), key=lambda e: e.edge_id)

    def nodes(self) -> list[Node]:
        return [self._nodes[k] for k in sorted(self._nodes)]

    def edges(self) -> list[Edge]:
        return [self._edges[k] for k in sorted(self._edges)]

    def __len__(self) -> int:
        return len(self._nodes)
