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

from textgraph.l0_ingest.base import UnsupportedFormat


def _renumber(community_of: dict[str, str], nodes: list[str]) -> dict[str, int]:
    """Compact raw labels to ints ordered by each group's smallest member (G1)."""
    groups: dict[str, list[str]] = defaultdict(list)
    for nid in nodes:
        groups[community_of[nid]].append(nid)
    ordered = sorted(groups.values(), key=lambda g: sorted(g)[0])
    out: dict[str, int] = {}
    for cid, members in enumerate(ordered):
        for nid in members:
            out[nid] = cid
    return out


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
    return _renumber(label, nodes)


def leiden_communities(
    node_ids: list[str], adj: dict[str, list[tuple[str, float]]], *, seed: int = 0
) -> dict[str, int]:
    """Higher-quality communities via Leiden — the import-guarded ``[graph]`` upgrade.

    Raises :class:`UnsupportedFormat` if ``igraph`` / ``leidenalg`` are absent, so the
    caller can fall back to :func:`label_propagation`. Seeded for reproducibility, and
    renumbered by smallest member so ids match the built-in convention.
    """
    try:
        import igraph
        import leidenalg
    except ImportError as exc:  # pragma: no cover - exercised only without [graph]
        raise UnsupportedFormat(
            "Leiden community detection requires the [graph] extra (igraph + leidenalg)"
        ) from exc

    nodes = sorted(node_ids)
    index = {nid: i for i, nid in enumerate(nodes)}
    seen: set[tuple[int, int]] = set()
    edges: list[tuple[int, int]] = []
    weights: list[float] = []
    for a in nodes:
        for b, w in adj.get(a, []):
            i, j = index[a], index[b]
            key = (i, j) if i < j else (j, i)
            if i == j or key in seen:
                continue
            seen.add(key)
            edges.append(key)
            weights.append(w)
    graph = igraph.Graph(n=len(nodes), edges=edges)
    partition = leidenalg.find_partition(
        graph,
        leidenalg.ModularityVertexPartition,
        weights=weights,
        seed=seed,
    )
    raw = {nodes[i]: str(partition.membership[i]) for i in range(len(nodes))}
    return _renumber(raw, nodes)


def detect_communities(
    node_ids: list[str],
    adj: dict[str, list[tuple[str, float]]],
    *,
    backend: str = "builtin",
    seed: int = 0,
) -> dict[str, int]:
    """Community detection with graceful fallback: ``leiden`` -> ``label_propagation``.

    The default ``builtin`` backend is pure-Python and CI-safe (G1). ``leiden`` is the
    opt-in accelerator; if its libraries are missing we fall back rather than fail.
    """
    if backend == "leiden":
        try:
            return leiden_communities(node_ids, adj, seed=seed)
        except UnsupportedFormat:
            pass
    return label_propagation(node_ids, adj)


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
