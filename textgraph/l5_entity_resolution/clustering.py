"""Clustering (L5, §8.3): form entity clusters without the over-merge catastrophe.

NOT naive connected components — one bad edge must not merge two galaxies. We use
complete-linkage agglomeration: two clusters merge only if *every* cross-pair scores
at least ``cohesion_min``. This bounds cluster cohesion and prevents transitive
chaining (a~b, b~c ⇒ a~c) from fusing dissimilar entities. Deterministic (G1).
"""

from __future__ import annotations

from collections.abc import Callable

from textgraph.l5_entity_resolution.model import ERecord


def cluster(
    records_by_id: dict[str, ERecord],
    matched_pairs: list[tuple[str, str, float]],
    score_fn: Callable[[ERecord, ERecord], float],
    *,
    cohesion_min: float,
) -> list[list[str]]:
    """Return clusters (size ≥ 2) of entity ids under complete-linkage cohesion."""
    parent: dict[str, str] = {rid: rid for rid in records_by_id}
    members: dict[str, list[str]] = {rid: [rid] for rid in records_by_id}

    def find(x: str) -> str:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:  # path compression
            parent[x], x = root, parent[x]
        return root

    # Strongest candidate edges first; deterministic tie-break by ids.
    for a, b, _score in sorted(matched_pairs, key=lambda p: (-p[2], p[0], p[1])):
        ra, rb = find(a), find(b)
        if ra == rb:
            continue
        ma, mb = members[ra], members[rb]
        cohesive = all(
            score_fn(records_by_id[x], records_by_id[y]) >= cohesion_min for x in ma for y in mb
        )
        if cohesive:
            parent[rb] = ra
            members[ra] = ma + mb
            del members[rb]

    return sorted(
        (sorted(m) for m in members.values() if len(m) > 1),
        key=lambda group: group[0],
    )
