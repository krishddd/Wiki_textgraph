"""Phase-1 graph diagnostics (degree-based only).

A deliberately small stand-in for L7 (Leiden communities, PageRank, betweenness),
which lands in Phase 4. Everything here is deterministic and model-free, enough to
drive the report's "god nodes", orphans, and suggested questions.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from textgraph.store.base import Edge, Node


@dataclass
class Diagnostics:
    degree: dict[str, int]
    by_label: dict[str, list[Node]]
    god_nodes: list[tuple[str, int]]
    orphans: list[Node]


def compute(nodes: list[Node], edges: list[Edge]) -> Diagnostics:
    degree: dict[str, int] = defaultdict(int)
    for e in edges:
        degree[e.subject] += 1
        degree[e.object] += 1

    by_label: dict[str, list[Node]] = defaultdict(list)
    for n in nodes:
        for label in n.labels:
            by_label[label].append(n)

    god_nodes = sorted(
        ((nid, deg) for nid, deg in degree.items()),
        key=lambda kv: (-kv[1], kv[0]),
    )[:10]

    connected = set(degree)
    orphans = sorted(
        (n for n in nodes if n.node_id not in connected),
        key=lambda n: n.node_id,
    )
    return Diagnostics(
        degree=dict(degree),
        by_label={k: by_label[k] for k in sorted(by_label)},
        god_nodes=god_nodes,
        orphans=orphans,
    )
