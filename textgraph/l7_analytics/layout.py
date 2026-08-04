"""Deterministic force-directed graph layout (L7), pure-Python.

Fruchterman-Reingold with community-aware gravity: repulsion spreads the graph,
edge attraction pulls related nodes together, and a gentle pull toward each
community's centroid makes the L7 clusters visually separate — the coloured islands
a reader expects from a knowledge-graph viewer.

**Computed server-side and deterministically** (G1): initial positions are derived
from a hash of each node id rather than a random seed, the iteration count is fixed,
and the final coordinates are rounded to a fixed precision. So the same graph always
lays out identically and the coordinates can be baked into a byte-identical
``graph.json``. The browser therefore only ever *draws* a layout — it never runs a
physics simulation, which is what keeps the viewer fast and the artifact stable.
"""

from __future__ import annotations

import math

from textgraph.core.content_address import hash_text

# Layout coordinates are rounded to this many decimals before they enter the graph,
# so last-digit float drift can never break the byte-identical gate (G1).
_PRECISION = 3


def _initial_positions(nodes: list[str], radius: float) -> dict[str, list[float]]:
    """Seed positions on a circle, deterministically perturbed by each node's hash.

    A pure circle would leave the simulation symmetric (and slow to resolve); the
    hash-derived offset breaks symmetry without introducing randomness.
    """
    pos: dict[str, list[float]] = {}
    n = max(1, len(nodes))
    for i, nid in enumerate(nodes):
        angle = 2.0 * math.pi * i / n
        # Two stable [0,1) values from the node id -> reproducible jitter.
        digest = hash_text(nid)
        jitter_r = int(digest[:8], 16) / 0xFFFFFFFF
        jitter_a = int(digest[8:16], 16) / 0xFFFFFFFF
        r = radius * (0.35 + 0.65 * jitter_r)
        a = angle + (jitter_a - 0.5) * 0.5
        pos[nid] = [r * math.cos(a), r * math.sin(a)]
    return pos


def force_layout(
    node_ids: list[str],
    adj: dict[str, list[tuple[str, float]]],
    *,
    community_of: dict[str, int] | None = None,
    iterations: int = 300,
    size: float = 1000.0,
    gravity: float = 0.02,
    community_gravity: float = 0.06,
) -> dict[str, tuple[float, float]]:
    """Lay out a graph in ``[-size/2, size/2]^2``; returns ``node_id -> (x, y)``.

    ``adj`` is the weighted adjacency from ``algorithms.build_adjacency``.
    ``community_of`` (from L7) adds per-cluster gravity so communities separate.
    Deterministic: sorted iteration, hash-seeded start, fixed iteration count.
    """
    nodes = sorted(node_ids)
    n = len(nodes)
    if n == 0:
        return {}
    if n == 1:
        return {nodes[0]: (0.0, 0.0)}

    half = size / 2.0
    pos = _initial_positions(nodes, half * 0.9)
    # Ideal edge length: the classic FR constant for the available area.
    k = math.sqrt((size * size) / n)
    temperature = size / 10.0
    cooling = temperature / (iterations + 1)

    for _ in range(iterations):
        disp: dict[str, list[float]] = {nid: [0.0, 0.0] for nid in nodes}

        # Repulsion between every pair (O(n^2); callers cap n for large graphs).
        for i, u in enumerate(nodes):
            ux, uy = pos[u]
            for v in nodes[i + 1 :]:
                vx, vy = pos[v]
                dx, dy = ux - vx, uy - vy
                dist_sq = dx * dx + dy * dy
                if dist_sq < 1e-9:
                    # Coincident nodes: push apart along a deterministic axis.
                    dx, dy, dist = 0.01, 0.0, 0.01
                else:
                    dist = math.sqrt(dist_sq)
                force = (k * k) / dist
                fx, fy = (dx / dist) * force, (dy / dist) * force
                disp[u][0] += fx
                disp[u][1] += fy
                disp[v][0] -= fx
                disp[v][1] -= fy

        # Attraction along edges (weight = confidence-ish; stronger edges pull harder).
        for u in nodes:
            ux, uy = pos[u]
            for v, w in adj.get(u, []):
                if v not in pos or v == u:
                    continue
                vx, vy = pos[v]
                dx, dy = ux - vx, uy - vy
                dist = math.sqrt(dx * dx + dy * dy) or 1e-6
                force = (dist * dist) / k * (0.5 + min(2.0, w))
                disp[u][0] -= (dx / dist) * force
                disp[u][1] -= (dy / dist) * force

        # Gravity to the origin keeps disconnected components on-screen.
        for nid in nodes:
            disp[nid][0] -= pos[nid][0] * gravity * k
            disp[nid][1] -= pos[nid][1] * gravity * k

        # Community gravity: pull each node toward its cluster's centroid.
        if community_of:
            centroids: dict[int, list[float]] = {}
            counts: dict[int, int] = {}
            for nid in nodes:
                cid = community_of.get(nid)
                if cid is None:
                    continue
                c = centroids.setdefault(cid, [0.0, 0.0])
                c[0] += pos[nid][0]
                c[1] += pos[nid][1]
                counts[cid] = counts.get(cid, 0) + 1
            for cid, c in centroids.items():
                c[0] /= counts[cid]
                c[1] /= counts[cid]
            for nid in nodes:
                cid = community_of.get(nid)
                if cid is None:
                    continue
                cx, cy = centroids[cid]
                disp[nid][0] -= (pos[nid][0] - cx) * community_gravity * k
                disp[nid][1] -= (pos[nid][1] - cy) * community_gravity * k

        # Apply displacement, capped by the current temperature, clamped to the frame.
        for nid in nodes:
            dx, dy = disp[nid]
            d = math.sqrt(dx * dx + dy * dy)
            if d > 1e-9:
                step = min(d, temperature)
                x = pos[nid][0] + (dx / d) * step
                y = pos[nid][1] + (dy / d) * step
                pos[nid][0] = max(-half, min(half, x))
                pos[nid][1] = max(-half, min(half, y))
        temperature = max(0.0, temperature - cooling)

    return {nid: (round(pos[nid][0], _PRECISION), round(pos[nid][1], _PRECISION)) for nid in nodes}
