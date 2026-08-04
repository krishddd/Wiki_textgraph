"""Fold L7 analytics back into the graph (node properties + CONTRADICTS edges).

:func:`compute_analytics` produces centrality/community/contradiction *findings*;
this module writes them onto the graph so they land in ``graph.json`` and are
queryable by L8. Entity nodes gain ``pagerank`` / ``betweenness`` / ``community`` /
``community_label`` properties, and each detected contradiction becomes a
``CONTRADICTS`` edge between the two reified :class:`Claim` nodes.

Floats are rounded to a fixed precision before they enter the graph so the artifact
stays byte-identical across rebuilds (G1). CONTRADICTS edges re-cite a relation's own
span, so provenance still re-verifies (G3).
"""

from __future__ import annotations

from dataclasses import replace

from textgraph.core.content_address import hash_text
from textgraph.l6_graph_model import claim_id_for
from textgraph.l7_analytics.analyze import Analytics
from textgraph.store.base import ConfidenceTag, Edge, Node

# Fixed precision for centrality scores written to the graph. Power-iteration output
# is deterministic on a given machine; rounding keeps it clean and guards the
# byte-identical gate against last-digit float drift.
_PRECISION = 8


def enrich_nodes(nodes: list[Node], analytics: Analytics) -> list[Node]:
    """Return nodes with centrality/community properties added to Entity nodes."""
    out: list[Node] = []
    for n in nodes:
        if "Entity" not in n.labels:
            out.append(n)
            continue
        cid = analytics.community_of.get(n.node_id)
        props = dict(n.properties)
        props["pagerank"] = round(analytics.pagerank.get(n.node_id, 0.0), _PRECISION)
        props["betweenness"] = round(analytics.betweenness.get(n.node_id, 0.0), _PRECISION)
        if cid is not None:
            props["community"] = cid
            props["community_label"] = analytics.community_labels.get(cid, "")
        out.append(replace(n, properties=props))
    return out


def contradiction_edges(edges: list[Edge], analytics: Analytics, claim_ids: set[str]) -> list[Edge]:
    """Emit a ``CONTRADICTS`` edge between the Claim nodes of each conflicting pair.

    ``claim_ids`` is the set of Claim node ids actually present in the graph; a pair
    whose claims were not reified (e.g. L6 disabled) is skipped rather than left
    pointing at phantom nodes.
    """
    by_id = {e.edge_id: e for e in edges}
    out: dict[str, Edge] = {}
    for eid_a, eid_b in analytics.contradictions:
        ea, eb = by_id.get(eid_a), by_id.get(eid_b)
        if ea is None or eb is None:
            continue
        claim_a, claim_b = claim_id_for(ea), claim_id_for(eb)
        if claim_a not in claim_ids or claim_b not in claim_ids:
            continue
        subject, obj = min(claim_a, claim_b), max(claim_a, claim_b)
        spans = tuple(ea.source_spans) + tuple(eb.source_spans)
        edge = Edge(
            edge_id="edge:" + hash_text(f"{subject}|CONTRADICTS|{obj}"),
            subject=subject,
            predicate="CONTRADICTS",
            object=obj,
            tag=ConfidenceTag.INFERRED,
            confidence=round(min(ea.confidence, eb.confidence), _PRECISION),
            evidence_count=len(spans),
            source_spans=spans,
            properties={"reason": "opposite polarity on the same subject/predicate/object"},
        )
        out.setdefault(edge.edge_id, edge)
    return sorted(out.values(), key=lambda e: e.edge_id)
