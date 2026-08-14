"""Deterministic structural link prediction (L7), pure-Python.

Given the entity relation graph, score entity pairs that are *not yet* connected by how
strongly the topology suggests a missing edge, using classic neighbourhood overlap indices:

* **Adamic-Adar** — shared neighbours weighted by ``1 / log(degree)``, so a rare shared
  neighbour counts far more than a hub everyone touches. This is the default.
* **Common-neighbours** — the raw count of shared neighbours.
* **Resource-allocation** — shared neighbours weighted by ``1 / degree`` (sharper than AA).

Only pairs at distance two (they share at least one neighbour) are considered, which is both
the standard formulation and what keeps the cost bounded: each node's contribution is
``O(sum of neighbour degrees)``. Everything is sorted deterministically, so predictions are
byte-reproducible (G1). Predictions are *suggestions*, never written into ``graph.json`` — the
console/CLI surface them as ``INFERRED`` candidates with the shared entities as evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_INDICES = ("adamic_adar", "common_neighbors", "resource_allocation")


@dataclass(frozen=True)
class LinkPrediction:
    """A predicted missing edge and why it was predicted."""

    source: str
    target: str
    score: float
    shared: tuple[str, ...]  # the common-neighbour node ids that drove the score


def _neighbors(adj: dict[str, list[str]]) -> dict[str, set[str]]:
    return {n: set(vs) for n, vs in adj.items()}


def predict_links(
    adj: dict[str, list[str]],
    *,
    index: str = "adamic_adar",
    k: int = 20,
    anchor: str | None = None,
) -> list[LinkPrediction]:
    """Rank the most likely missing edges in an undirected adjacency map.

    ``adj`` maps each node id to its neighbour ids. ``anchor`` restricts predictions to pairs
    incident to that node (the console's per-node "predict links"); ``None`` ranks globally.
    Returns the top ``k`` predictions, highest score first (ties broken by node id).
    """
    if index not in _INDICES:
        raise ValueError(f"unknown index {index!r}; choose one of {_INDICES}")
    nbr = _neighbors(adj)
    deg = {n: len(vs) for n, vs in nbr.items()}

    def weight(w: str) -> float:
        d = deg.get(w, 0)
        if index == "common_neighbors":
            return 1.0
        if index == "resource_allocation":
            return 1.0 / d if d else 0.0
        return 1.0 / math.log(d) if d > 1 else 0.0  # adamic_adar

    sources = [anchor] if anchor is not None else sorted(nbr)
    if anchor is not None and anchor not in nbr:
        return []
    scores: dict[tuple[str, str], float] = {}
    shared: dict[tuple[str, str], list[str]] = {}
    for u in sources:
        two_hop: dict[str, list[str]] = {}
        for w in nbr.get(u, ()):  # walk u -> w -> v; v is a distance-2 candidate
            for v in nbr.get(w, ()):
                if v == u or v in nbr[u]:  # already u's neighbour (or u itself) -> not missing
                    continue
                two_hop.setdefault(v, []).append(w)
        for v, commons in two_hop.items():
            key = (u, v) if u < v else (v, u)
            if key in scores:  # a global run reaches each unordered pair from both ends
                continue
            s = sum(weight(w) for w in commons)
            if s > 0:
                scores[key] = round(s, 6)
                shared[key] = sorted(commons)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
    return [
        LinkPrediction(source=a, target=b, score=s, shared=tuple(shared[(a, b)]))
        for (a, b), s in ranked
    ]
