"""Entity-resolution metrics (L5, §8.4).

B-cubed precision/recall/F1 (pairwise metrics lie about over-merging, so B-cubed is
the gate), plus blocking recall and reduction ratio for the blocking stage.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations


def bcubed(pred: dict[str, str], gold: dict[str, str]) -> tuple[float, float, float]:
    """B-cubed (precision, recall, F1) over elements labelled by cluster id.

    ``pred``/``gold`` map each entity id to its cluster label (singletons allowed).
    Both must cover the same element set.
    """
    elems = sorted(gold)
    if not elems:
        return 1.0, 1.0, 1.0
    pred_c: dict[str, set[str]] = defaultdict(set)
    gold_c: dict[str, set[str]] = defaultdict(set)
    for e in elems:
        pred_c[pred[e]].add(e)
        gold_c[gold[e]].add(e)
    precision = recall = 0.0
    for e in elems:
        pe, ge = pred_c[pred[e]], gold_c[gold[e]]
        inter = len(pe & ge)
        precision += inter / len(pe)
        recall += inter / len(ge)
    n = len(elems)
    precision /= n
    recall /= n
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def true_pairs(gold: dict[str, str]) -> set[tuple[str, str]]:
    """All same-cluster id pairs implied by a gold labelling (id_a < id_b)."""
    by_cluster: dict[str, list[str]] = defaultdict(list)
    for eid, label in gold.items():
        by_cluster[label].append(eid)
    pairs: set[tuple[str, str]] = set()
    for ids in by_cluster.values():
        for a, b in combinations(sorted(ids), 2):
            pairs.add((a, b))
    return pairs


def blocking_recall(candidate_pairs: list[tuple[str, str]], gold: dict[str, str]) -> float:
    truth = true_pairs(gold)
    if not truth:
        return 1.0
    cand = set(candidate_pairs)
    return len(truth & cand) / len(truth)


def reduction_ratio(candidate_count: int, cross_product: int) -> float:
    if cross_product <= 0:
        return 1.0
    return 1.0 - candidate_count / cross_product
