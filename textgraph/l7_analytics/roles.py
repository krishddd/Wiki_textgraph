"""Structural role similarity — 'find entities that play the same role as X' (deterministic).

Shell companies replicate a *shape*: one controller in, money out to several fronts, little
inbound trade. Role similarity surfaces the next entity with that shape even when it shares no
name, document, or neighbor with the known one — the opposite of proximity search.

We do this with **deterministic structural signatures**, not Node2Vec: a fixed vector of local
topology invariants per entity (degree structure, centrality, clustering, neighbor-degree stats,
and the normalized mix of relation types it participates in), z-scored across the graph and
compared by cosine. Every feature is a closed-form, sorted function of the graph — no random
walks, no training, no dependency, so the ranking is reproducible (G1). See
``docs/plans/structural-roles.md`` for why this beats Node2Vec here.

Query-time only: reads the built graph, never writes ``graph.json``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from textgraph.store.base import Edge, Node

_PLUMBING = frozenset(
    {"MENTIONS", "HAS_CHUNK", "SUBJECT_OF", "HAS_OBJECT", "CONTAINS", "SAME_AS", "CONTRADICTS"}
)

# The fixed scalar features, in order. Kept explicit so a signature is interpretable.
_SCALARS = (
    "in_degree",
    "out_degree",
    "total_degree",
    "weighted_degree",
    "pagerank",
    "betweenness",
    "clustering",
    "neighbor_mean_degree",
    "neighbor_max_degree",
    "distinct_relation_types",
)


@dataclass
class RoleSignature:
    """One entity's raw structural features (before normalization) + its dominant relations."""

    node_id: str
    name: str
    scalars: dict[str, float] = field(default_factory=dict)
    profile: dict[str, float] = field(default_factory=dict)  # predicate -> fraction

    def top_relations(self, k: int = 3) -> list[str]:
        return [p for p, _ in sorted(self.profile.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def _relation_edges(edges: list[Edge]) -> list[Edge]:
    return [e for e in edges if e.predicate not in _PLUMBING and e.subject != e.object]


def compute_signatures(nodes: list[Node], edges: list[Edge]) -> dict[str, RoleSignature]:
    """Raw structural signature per entity — deterministic, order-independent."""
    ent = {n.node_id: n for n in nodes if "Entity" in n.labels}
    rels = _relation_edges(edges)

    out_adj: dict[str, set[str]] = {nid: set() for nid in ent}
    in_adj: dict[str, set[str]] = {nid: set() for nid in ent}
    undirected: dict[str, set[str]] = {nid: set() for nid in ent}
    weighted: dict[str, float] = dict.fromkeys(ent, 0.0)
    predicates: dict[str, dict[str, int]] = {nid: {} for nid in ent}
    for e in rels:
        if e.subject not in ent or e.object not in ent:
            continue
        out_adj[e.subject].add(e.object)
        in_adj[e.object].add(e.subject)
        undirected[e.subject].add(e.object)
        undirected[e.object].add(e.subject)
        weighted[e.subject] += e.confidence
        weighted[e.object] += e.confidence
        for endpoint in (e.subject, e.object):
            predicates[endpoint][e.predicate] = predicates[endpoint].get(e.predicate, 0) + 1

    deg = {nid: len(undirected[nid]) for nid in ent}

    def _clustering(nid: str) -> float:
        nbrs = sorted(undirected[nid])
        if len(nbrs) < 2:
            return 0.0
        links = 0
        for i, a in enumerate(nbrs):
            for b in nbrs[i + 1 :]:
                if b in undirected[a]:
                    links += 1
        possible = len(nbrs) * (len(nbrs) - 1) / 2
        return links / possible if possible else 0.0

    sigs: dict[str, RoleSignature] = {}
    for nid in sorted(ent):
        nbrs = undirected[nid]
        nbr_degs = [deg[m] for m in sorted(nbrs)] or [0]
        props = ent[nid].properties
        total_rel = sum(predicates[nid].values()) or 1
        scalars = {
            "in_degree": float(len(in_adj[nid])),
            "out_degree": float(len(out_adj[nid])),
            "total_degree": float(deg[nid]),
            "weighted_degree": round(weighted[nid], 6),
            "pagerank": float(props.get("pagerank", 0.0)),
            "betweenness": float(props.get("betweenness", 0.0)),
            "clustering": round(_clustering(nid), 6),
            "neighbor_mean_degree": round(sum(nbr_degs) / len(nbr_degs), 6),
            "neighbor_max_degree": float(max(nbr_degs)),
            "distinct_relation_types": float(len(predicates[nid])),
        }
        profile = {p: c / total_rel for p, c in predicates[nid].items()}
        sigs[nid] = RoleSignature(
            node_id=nid,
            name=str(props.get("name", nid)),
            scalars=scalars,
            profile=profile,
        )
    return sigs


def _vectorize(sigs: dict[str, RoleSignature]) -> tuple[list[str], dict[str, list[float]]]:
    """Assemble z-scored feature vectors over a fixed dimension order (scalars + predicates)."""
    ids = sorted(sigs)
    predicates = sorted({p for s in sigs.values() for p in s.profile})
    dims = list(_SCALARS) + [f"rel:{p}" for p in predicates]

    raw: dict[str, list[float]] = {}
    for nid in ids:
        s = sigs[nid]
        vec = [s.scalars[name] for name in _SCALARS]
        vec += [s.profile.get(p, 0.0) for p in predicates]
        raw[nid] = vec

    # z-score each dimension across nodes; a zero-variance dimension contributes nothing.
    n = len(ids)
    for d in range(len(dims)):
        col = [raw[nid][d] for nid in ids]
        mean = sum(col) / n
        var = sum((x - mean) ** 2 for x in col) / n
        std = math.sqrt(var)
        if std == 0.0:
            for nid in ids:
                raw[nid][d] = 0.0
        else:
            for nid in ids:
                raw[nid][d] = (raw[nid][d] - mean) / std
    return dims, raw


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def role_similarity(
    sigs: dict[str, RoleSignature], anchor_id: str, *, k: int = 10
) -> list[dict[str, Any]]:
    """Rank entities by structural-role similarity to ``anchor_id`` (cosine over signatures).

    Deterministic: fixed dimension order, sorted ids, and ties broken by node id. Returns the
    top ``k`` peers (excluding the anchor) with their similarity and dominant relations, so a
    result is interpretable ("this one matches because it also mostly TRANSFERRED / CONTROLS").
    """
    if anchor_id not in sigs:
        return []
    _dims, vecs = _vectorize(sigs)
    anchor = vecs[anchor_id]
    scored = []
    for nid in sorted(sigs):
        if nid == anchor_id:
            continue
        sim = _cosine(anchor, vecs[nid])
        scored.append((round(sim, 6), nid))
    scored.sort(key=lambda t: (-t[0], t[1]))
    out: list[dict[str, Any]] = []
    for sim, nid in scored[:k]:
        s = sigs[nid]
        out.append(
            {
                "node_id": nid,
                "name": s.name,
                "similarity": sim,
                "total_degree": int(s.scalars["total_degree"]),
                "top_relations": s.top_relations(),
            }
        )
    return out
