"""Graph storage abstraction.

Nothing above L6 may touch a concrete backend (NetworkX, DuckDB, ...) directly;
all access goes through :class:`GraphStore` so the on-disk engine can be swapped
(GQL-native engine in Phase 7) without changing L6/L7/L8 call sites.
"""

from textgraph.store.base import Edge, GraphStore, Node

__all__ = ["Edge", "GraphStore", "Node"]
