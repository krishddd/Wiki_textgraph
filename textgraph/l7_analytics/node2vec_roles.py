"""Learned Node2Vec role embeddings — the opt-in ``[graph]`` backend for role similarity.

The default role similarity (``roles.py``) is deterministic structural signatures — the moat-safe
choice, and the console/CLI default. This module is the **opt-in learned alternative** for users
who explicitly want Node2Vec embeddings and accept the trade-offs it makes against the moat:

* it is **stochastic** (biased random walks + skip-gram), so results are *best-effort*
  reproducible — we pin the seed and force ``workers=1``, but exact byte-reproducibility across
  machines/library versions is not guaranteed the way the deterministic backend is;
* it captures graph **proximity** more than pure structural role, so it complements rather than
  replaces the signature backend.

It is import-guarded behind the ``[graph]`` extra (``pip install 'textgraph-kg[graph]'``): the
default install never imports it, and asking for ``backend="node2vec"`` without the extra raises a
clear error instead of a stack trace. Query-time only; ``graph.json`` is untouched. See
``docs/plans/structural-roles.md`` for why the *default* stays deterministic.
"""

from __future__ import annotations

from typing import Any

from textgraph.l0_ingest.base import UnsupportedFormat
from textgraph.store.base import Edge, Node

_PLUMBING = frozenset(
    {"MENTIONS", "HAS_CHUNK", "SUBJECT_OF", "HAS_OBJECT", "CONTAINS", "SAME_AS", "CONTRADICTS"}
)


def node2vec_similarity(
    nodes: list[Node],
    edges: list[Edge],
    anchor_id: str,
    *,
    k: int = 10,
    seed: int = 0,
    dimensions: int = 64,
) -> list[dict[str, Any]]:
    """Rank entities by learned Node2Vec-embedding similarity to ``anchor_id``.

    Raises :class:`UnsupportedFormat` if the ``[graph]`` extra (``networkx`` + ``node2vec``) is
    absent, so the caller can fall back to the deterministic backend with a clear message. Seeded
    and single-worker for best-effort reproducibility.
    """
    try:
        import networkx as nx
        from node2vec import Node2Vec
    except ImportError as exc:  # pragma: no cover - exercised only without [graph]
        raise UnsupportedFormat(
            "Node2Vec role embeddings need the [graph] extra: pip install 'textgraph-kg[graph]'"
        ) from exc

    ent = {n.node_id for n in nodes if "Entity" in n.labels}
    names = {n.node_id: str(n.properties.get("name", n.node_id)) for n in nodes}
    if anchor_id not in ent:
        return []

    graph = nx.Graph()
    graph.add_nodes_from(sorted(ent))  # sorted for a stable node order
    for e in edges:
        if e.predicate in _PLUMBING or e.subject == e.object:
            continue
        if e.subject in ent and e.object in ent:
            graph.add_edge(e.subject, e.object, weight=float(e.confidence))
    if graph.number_of_edges() == 0:
        return []

    n2v = Node2Vec(
        graph,
        dimensions=dimensions,
        walk_length=10,
        num_walks=20,
        workers=1,  # single worker: required for reproducibility
        seed=seed,
        quiet=True,
    )
    model = n2v.fit(window=5, min_count=1, seed=seed, workers=1)

    if anchor_id not in model.wv:
        return []
    # gensim's own cosine-similarity ranking over the learned vectors.
    ranked = model.wv.most_similar(anchor_id, topn=k + 1)
    out: list[dict[str, Any]] = []
    for nid, sim in ranked:
        if nid == anchor_id:
            continue
        out.append(
            {
                "node_id": nid,
                "name": names.get(nid, nid),
                "similarity": round(float(sim), 6),
                "total_degree": graph.degree(nid) if nid in graph else 0,
                "top_relations": [],  # learned embedding: no interpretable relation profile
            }
        )
        if len(out) >= k:
            break
    return out
