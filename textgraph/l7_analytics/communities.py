"""Community detection + labelling (L7), deterministic and model-free.

Asynchronous label propagation with a fixed node order and smallest-label tie-break
(reproducible, G1), then c-TF-IDF + MMR labelling — auto-labels without an LLM,
matching Graphify's differentiator. Leiden (``leidenalg``) is the higher-quality
option behind the ``[graph]`` extra.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]{2,}")
_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "was",
        "are",
        "has",
        "have",
        "not",
        "all",
        "any",
        "its",
        "into",
        "per",
        "via",
        "inc",
        "ltd",
        "corp",
        "llc",
        "organization",
        "person",
        "entity",
        "section",
        "document",
    }
)


def label_propagation(
    node_ids: list[str],
    adj: dict[str, list[tuple[str, float]]],
    *,
    iterations: int = 20,
) -> dict[str, int]:
    """Assign each node an integer community id via deterministic LPA."""
    nodes = sorted(node_ids)
    label = {nid: nid for nid in nodes}
    for _ in range(iterations):
        changed = False
        for nid in nodes:
            if not adj.get(nid):
                continue
            weights: dict[str, float] = defaultdict(float)
            for nbr, w in adj[nid]:
                weights[label[nbr]] += w
            # Most weight, tie-break by smallest label string.
            best = min(weights.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            if best != label[nid]:
                label[nid] = best
                changed = True
        if not changed:
            break
    # Renumber to compact, deterministic ints ordered by smallest member.
    groups: dict[str, list[str]] = defaultdict(list)
    for nid in nodes:
        groups[label[nid]].append(nid)
    ordered = sorted(groups.values(), key=lambda g: sorted(g)[0])
    community_of: dict[str, int] = {}
    for cid, members in enumerate(ordered):
        for nid in members:
            community_of[nid] = cid
    return community_of


def label_communities(
    community_of: dict[str, int],
    names: dict[str, str],
    centrality: dict[str, float],
    *,
    top_k: int = 3,
) -> dict[int, str]:
    """c-TF-IDF labels: distinctive terms per community + its most central member."""
    members: dict[int, list[str]] = defaultdict(list)
    for nid, cid in community_of.items():
        members[cid].append(nid)

    # Term frequencies per community and globally.
    comm_tf: dict[int, Counter[str]] = {}
    global_df: Counter[str] = Counter()
    for cid, ids in members.items():
        tf: Counter[str] = Counter()
        for nid in ids:
            for tok in _TOKEN.findall(names.get(nid, "").lower()):
                if tok not in _STOP:
                    tf[tok] += 1
        comm_tf[cid] = tf
        for tok in tf:
            global_df[tok] += 1

    n_comm = max(1, len(members))
    labels: dict[int, str] = {}
    for cid, ids in members.items():
        tf = comm_tf[cid]
        scored = sorted(
            ((tok, freq * math.log(1 + n_comm / (1 + global_df[tok]))) for tok, freq in tf.items()),
            key=lambda kv: (-kv[1], kv[0]),
        )
        terms = [tok for tok, _ in scored[:top_k]]
        central = max(ids, key=lambda nid: (centrality.get(nid, 0.0), nid))
        central_name = names.get(central, central)
        if terms:
            labels[cid] = f"{', '.join(terms)} ({central_name})"
        else:
            labels[cid] = central_name
    return labels
