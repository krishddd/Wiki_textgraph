"""Blocking (L5, §8.1): reduce the O(n²) cross-product to candidate pairs.

Deterministic blocking keys, unioned: suffix-stripped normalized name, acronym,
and first-token. Type-gated (never compare a Person to an Organization). Target:
recall ≥ 0.99 on true pairs at a small fraction of the cross-product.
"""

from __future__ import annotations

from collections.abc import Iterable
from itertools import combinations

from textgraph.l5_entity_resolution.model import ERecord


def _keys(rec: ERecord) -> set[str]:
    keys = {f"strip:{rec.etype}:{rec.stripped}"}
    if rec.acronym:
        keys.add(f"acr:{rec.etype}:{rec.acronym}")
    # An all-caps short name (ACME) blocks with a same-typed stripped name it prefixes.
    toks = rec.stripped.split()
    if toks:
        keys.add(f"tok0:{rec.etype}:{toks[0]}")
    return keys


def candidate_pairs(records: Iterable[ERecord]) -> list[tuple[str, str]]:
    """Return deterministically-ordered unique candidate id pairs (id_a < id_b)."""
    records = list(records)
    buckets: dict[str, list[str]] = {}
    for rec in records:
        for key in _keys(rec):
            buckets.setdefault(key, []).append(rec.entity_id)

    pairs: set[tuple[str, str]] = set()
    for ids in buckets.values():
        for a, b in combinations(sorted(set(ids)), 2):
            pairs.add((a, b))
    return sorted(pairs)


def cross_product(n: int) -> int:
    return n * (n - 1) // 2
