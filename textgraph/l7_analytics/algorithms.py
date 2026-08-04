"""Deterministic graph algorithms (L7), pure-Python.

PageRank / Personalized PageRank via power iteration, Brandes betweenness, and
connected components. No external deps, fixed iteration order and dangling-mass
handling, so results are byte-reproducible (G1). ``leidenalg``/``igraph`` and
``scipy.sparse`` are optional accelerators behind the ``[graph]`` extra; these are
the CI-safe default.
"""

from __future__ import annotations

from collections import deque


def build_adjacency(
    node_ids: list[str], edges: list[tuple[str, str, float]]
) -> dict[str, list[tuple[str, float]]]:
    """Undirected weighted adjacency (sorted), restricted to known nodes."""
    known = set(node_ids)
    adj: dict[str, list[tuple[str, float]]] = {n: [] for n in node_ids}
    for a, b, w in edges:
        if a in known and b in known and a != b:
            adj[a].append((b, w))
            adj[b].append((a, w))
    for n in adj:
        adj[n].sort()
    return adj


def pagerank(
    node_ids: list[str],
    adj: dict[str, list[tuple[str, float]]],
    *,
    damping: float = 0.85,
    iterations: int = 100,
    tol: float = 1e-9,
    personalization: dict[str, float] | None = None,
) -> dict[str, float]:
    """Weighted PageRank / Personalized PageRank via power iteration.

    ``personalization`` (a non-normalized seed distribution) turns this into PPR;
    when omitted it is uniform. Deterministic: fixed node order, explicit dangling
    redistribution.
    """
    n = len(node_ids)
    if n == 0:
        return {}
    nodes = sorted(node_ids)
    idx = {nid: i for i, nid in enumerate(nodes)}

    if personalization:
        total = sum(max(0.0, personalization.get(nid, 0.0)) for nid in nodes)
        if total <= 0:
            teleport = [1.0 / n] * n
        else:
            teleport = [max(0.0, personalization.get(nid, 0.0)) / total for nid in nodes]
    else:
        teleport = [1.0 / n] * n

    out_weight = [sum(w for _, w in adj.get(nid, [])) for nid in nodes]
    rank = list(teleport)
    for _ in range(iterations):
        new = [0.0] * n
        dangling = 0.0
        for i in range(n):
            if out_weight[i] <= 0:
                dangling += rank[i]
        for i in range(n):
            share = damping * dangling * teleport[i]
            new[i] = (1.0 - damping) * teleport[i] + share
        for i, nid in enumerate(nodes):
            if out_weight[i] <= 0:
                continue
            contrib = damping * rank[i] / out_weight[i]
            for nbr, w in adj[nid]:
                new[idx[nbr]] += contrib * w
        delta = sum(abs(new[i] - rank[i]) for i in range(n))
        rank = new
        if delta < tol:
            break
    return {nid: rank[i] for i, nid in enumerate(nodes)}


def betweenness(node_ids: list[str], adj: dict[str, list[tuple[str, float]]]) -> dict[str, float]:
    """Brandes betweenness centrality (unweighted, normalized). O(VE)."""
    nodes = sorted(node_ids)
    cb = dict.fromkeys(nodes, 0.0)
    neighbors = {nid: [b for b, _ in adj.get(nid, [])] for nid in nodes}
    for s in nodes:
        stack: list[str] = []
        pred: dict[str, list[str]] = {w: [] for w in nodes}
        sigma = dict.fromkeys(nodes, 0.0)
        sigma[s] = 1.0
        dist = dict.fromkeys(nodes, -1)
        dist[s] = 0
        queue: deque[str] = deque([s])
        while queue:
            v = queue.popleft()
            stack.append(v)
            for w in neighbors[v]:
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    queue.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)
        delta = dict.fromkeys(nodes, 0.0)
        while stack:
            w = stack.pop()
            for v in pred[w]:
                if sigma[w] > 0:
                    delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                cb[w] += delta[w]
    scale = (len(nodes) - 1) * (len(nodes) - 2)
    if scale > 0:
        for w in cb:
            cb[w] /= scale
    return cb


def connected_components(
    node_ids: list[str], adj: dict[str, list[tuple[str, float]]]
) -> list[list[str]]:
    """Connected components as sorted lists, ordered by smallest member."""
    seen: set[str] = set()
    components: list[list[str]] = []
    for start in sorted(node_ids):
        if start in seen:
            continue
        comp: list[str] = []
        queue: deque[str] = deque([start])
        seen.add(start)
        while queue:
            v = queue.popleft()
            comp.append(v)
            for w, _ in adj.get(v, []):
                if w not in seen:
                    seen.add(w)
                    queue.append(w)
        components.append(sorted(comp))
    return sorted(components, key=lambda c: c[0])


def is_bridge(a: str, b: str, adj: dict[str, list[tuple[str, float]]]) -> bool:
    """True if removing edge (a, b) disconnects b from a (a bridge / structural hole)."""
    seen = {a}
    queue: deque[str] = deque([a])
    while queue:
        v = queue.popleft()
        for w, _ in adj.get(v, []):
            if (v == a and w == b) or (v == b and w == a):
                continue  # skip the edge under test
            if w not in seen:
                seen.add(w)
                queue.append(w)
    return b not in seen
