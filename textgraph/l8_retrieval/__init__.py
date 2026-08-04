"""L8 — retrieval surface.

Hybrid BM25 + Personalized-PageRank retrieval over a dual-node (entity + chunk)
graph, exposed as eight typed, bounded, cited tools via :class:`QueryEngine`. The
CLI and the MCP server are two thin formatters over this one engine. See
:mod:`textgraph.l8_retrieval.engine`.
"""

from textgraph.l8_retrieval.engine import QueryEngine, engine_from_path

__all__ = ["QueryEngine", "engine_from_path"]
