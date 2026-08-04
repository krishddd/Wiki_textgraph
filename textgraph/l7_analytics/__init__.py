"""L7 — Graph Analytics.

Deterministic PageRank / betweenness, label-propagation communities with c-TF-IDF
labels, and diagnostics (god nodes, bridges, orphans, contradictions). Pure-Python
and CI-safe; Leiden is the optional ``[graph]`` upgrade. See ARCHITECTURE.md.
"""

from textgraph.l7_analytics.analyze import Analytics, compute_analytics

__all__ = ["Analytics", "compute_analytics"]
