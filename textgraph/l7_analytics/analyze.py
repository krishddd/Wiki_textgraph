"""L7 orchestration — turn the assembled entity graph into analytics + diagnostics.

Builds a weighted, undirected entity graph (edge weight ``confidence * log(1 +
evidence_count)`` — a relation trusted more and cited more often pulls harder),
then runs the deterministic PageRank, Brandes betweenness, and label-propagation
communities from :mod:`textgraph.l7_analytics.algorithms` /
:mod:`~textgraph.l7_analytics.communities`. On top of those it derives the
investigator-facing diagnostics: god nodes (central on *both* PageRank and
betweenness), bridges (inter-community edges whose removal disconnects), orphans
(degree-0 entities), and contradictions (same subject/predicate/object asserted
with opposite polarity).

Everything here is pure-Python and deterministic (G1): iteration is over sorted
ids, there is no wall-clock or randomness, so the analytics fold into a
byte-identical ``graph.json``. Feeds L8 retrieval tools (``communities``,
``contradictions``) and the L9 report.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from textgraph.l7_analytics.algorithms import (
    betweenness,
    build_adjacency,
    is_bridge,
    pagerank,
)
from textgraph.l7_analytics.communities import detect_communities, label_communities
from textgraph.l7_analytics.layout import force_layout
from textgraph.store.base import Edge, Node


@dataclass
class Analytics:
    """Computed graph analytics over the entity subgraph (all deterministic)."""

    pagerank: dict[str, float] = field(default_factory=dict)
    betweenness: dict[str, float] = field(default_factory=dict)
    community_of: dict[str, int] = field(default_factory=dict)
    community_labels: dict[int, str] = field(default_factory=dict)
    god_nodes: list[str] = field(default_factory=list)
    bridges: list[tuple[str, str]] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    # Each contradiction is a sorted pair of relation edge ids asserting the same
    # (subject, predicate, object) with opposite polarity.
    contradictions: list[tuple[str, str]] = field(default_factory=list)
    # Deterministic force-directed coordinates per entity, for the graph viewer.
    positions: dict[str, tuple[float, float]] = field(default_factory=dict)


def _entity_adjacency(
    nodes: list[Node], edges: list[Edge]
) -> tuple[list[str], dict[str, list[tuple[str, float]]]]:
    """Weighted undirected adjacency over Entity nodes only.

    An edge joins two entities when both its endpoints are entity nodes (this keeps
    ``doc: -> entity`` MENTIONS out of the centrality graph while retaining relations
    and SAME_AS links). Weight rewards trust and repetition: ``confidence * log(1 +
    evidence_count)``.
    """
    entity_ids = sorted(n.node_id for n in nodes if "Entity" in n.labels)
    known = set(entity_ids)
    weighted: list[tuple[str, str, float]] = []
    for e in edges:
        if e.subject in known and e.object in known and e.subject != e.object:
            weight = e.confidence * math.log1p(max(0, e.evidence_count))
            weighted.append((e.subject, e.object, weight))
    return entity_ids, build_adjacency(entity_ids, weighted)


def _god_nodes(pr: dict[str, float], bc: dict[str, float], *, top_k: int) -> list[str]:
    """Nodes central on *both* PageRank and betweenness (structural power).

    Degree centrality alone flags hubs; a node that is also a betweenness
    bottleneck is a genuine controller/broker. Ordered by PageRank descending.
    """
    top_pr = {nid for nid, _ in sorted(pr.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]}
    top_bc = {nid for nid, _ in sorted(bc.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]}
    both = top_pr & top_bc
    return sorted(both, key=lambda nid: (-pr.get(nid, 0.0), nid))


def _bridges(
    adj: dict[str, list[tuple[str, float]]], community_of: dict[str, int]
) -> list[tuple[str, str]]:
    """Inter-community edges whose removal disconnects their endpoints.

    A bridge between two communities is a structural hole — the single conduit an
    investigator would watch or an adversary would sever. Tested only on
    inter-community edges (intra-community bridges are rarely the interesting kind).
    """
    seen: set[tuple[str, str]] = set()
    for a in sorted(adj):
        for b, _ in adj[a]:
            pair = (a, b) if a < b else (b, a)
            if pair in seen:
                continue
            if community_of.get(a) == community_of.get(b):
                continue
            if is_bridge(pair[0], pair[1], adj):
                seen.add(pair)
    return sorted(seen)


def _contradictions(edges: list[Edge]) -> list[tuple[str, str]]:
    """Relation edge pairs with equal (subject, predicate, object) but opposite polarity.

    "X transferred to Y" and "X did not transfer to Y" both surviving IE is a
    conflict worth flagging, not silently reconciling (§6.4 — surface, cite, let the
    investigator judge).
    """
    by_triple: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    for e in edges:
        polarity = e.properties.get("polarity")
        if polarity not in ("pos", "neg"):
            continue
        key = (e.subject, e.predicate, e.object)
        by_triple.setdefault(key, []).append((str(polarity), e.edge_id))

    pairs: list[tuple[str, str]] = []
    for members in by_triple.values():
        pos = sorted(eid for pol, eid in members if pol == "pos")
        neg = sorted(eid for pol, eid in members if pol == "neg")
        for p in pos:
            for n in neg:
                pairs.append((p, n) if p < n else (n, p))
    return sorted(pairs)


def compute_analytics(
    nodes: list[Node], edges: list[Edge], *, top_k: int = 10, backend: str = "builtin"
) -> Analytics:
    """Run L7 analytics + diagnostics over the assembled graph (deterministic).

    ``backend`` selects the community algorithm: ``builtin`` (label propagation,
    CI-safe) or ``leiden`` (the ``[graph]`` upgrade, falling back if unavailable).
    """
    entity_ids, adj = _entity_adjacency(nodes, edges)
    if not entity_ids:
        return Analytics()

    names = {n.node_id: str(n.properties.get("name", n.node_id)) for n in nodes}

    pr = pagerank(entity_ids, adj)
    bc = betweenness(entity_ids, adj)
    community_of = detect_communities(entity_ids, adj, backend=backend)
    community_labels = label_communities(community_of, names, pr)

    god_nodes = _god_nodes(pr, bc, top_k=top_k)
    bridges = _bridges(adj, community_of)
    orphans = sorted(nid for nid in entity_ids if not adj.get(nid))
    contradictions = _contradictions(edges)
    # Fewer iterations for very large graphs keeps the O(n^2) pass bounded (G7).
    iters = 300 if len(entity_ids) <= 400 else 120
    positions = force_layout(entity_ids, adj, community_of=community_of, iterations=iters)

    return Analytics(
        pagerank=pr,
        betweenness=bc,
        community_of=community_of,
        community_labels=community_labels,
        god_nodes=god_nodes,
        bridges=bridges,
        orphans=orphans,
        contradictions=contradictions,
        positions=positions,
    )
