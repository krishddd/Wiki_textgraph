"""L6 — claim reification (the assertion becomes a first-class node).

Every extracted relation edge ("Acme TRANSFERRED Beta") is *also* reified into a
``Claim`` node carrying the full assertion: subject, predicate, object, confidence,
polarity, modality, and a temporal validity window (``t_valid`` / ``t_invalid``).
The original direct edge is kept, so graph traversal is unchanged; the Claim node is
what makes ``why`` / ``contradictions`` / ``timeline`` answerable — you can point at
the assertion itself, cite it, and reason about *when* it held.

Temporal grounding here is deliberately shallow (full bi-temporal invalidation is
Phase 5): ``t_valid`` is the nearest ``Date`` entity mentioned in the same sentence
as the relation (by byte proximity), else null; ``t_invalid`` is always null for
now. No wall-clock ever enters the graph — the only dates are ones the corpus itself
states — so ``graph.json`` stays byte-identical across rebuilds (G1). Every reified
edge re-cites the relation's own byte span, so provenance still re-verifies (G3).
"""

from __future__ import annotations

from dataclasses import dataclass

from textgraph.core.content_address import hash_text
from textgraph.store.base import ConfidenceTag, Edge, Node, SourceSpan

# A relation edge is one that asserts something *between two entities*. Identity
# (SAME_AS) and doc-membership (MENTIONS) are not assertions to reify.
_NON_CLAIM_PREDICATES = frozenset({"SAME_AS", "MENTIONS"})

# How far (raw bytes) a Date mention may sit from a relation span and still count as
# "in the same sentence". Sentences in the investigator corpora run well under this.
_DATE_WINDOW = 160


@dataclass(frozen=True)
class _DateMention:
    doc_id: str
    start: int
    end: int
    name: str


def claim_id_for(edge: Edge) -> str:
    """Deterministic id of the Claim reifying ``edge`` (stable across rebuilds).

    Keyed on the assertion triple plus the citing byte span, so re-running L6 over
    the same edge yields the same claim id — and L7 can recompute it to wire
    ``CONTRADICTS`` between claims without threading a mapping through.
    """
    span = edge.source_spans[0] if edge.source_spans else None
    key = f"{edge.subject}|{edge.predicate}|{edge.object}"
    if span is not None:
        key += f"|{span.doc_id}|{span.start}|{span.end}"
    return "claim:" + hash_text(key)


def is_relation_edge(edge: Edge, entity_ids: frozenset[str]) -> bool:
    """True if ``edge`` is an entity-to-entity assertion worth reifying."""
    return (
        edge.predicate not in _NON_CLAIM_PREDICATES
        and edge.subject in entity_ids
        and edge.object in entity_ids
    )


def _date_mentions(nodes: list[Node], edges: list[Edge]) -> dict[str, list[_DateMention]]:
    """Map doc_id -> sorted Date-entity mentions, drawn from doc->Date MENTIONS spans."""
    date_ids = {n.node_id for n in nodes if "Date" in n.labels}
    names = {n.node_id: str(n.properties.get("name", n.node_id)) for n in nodes}
    by_doc: dict[str, list[_DateMention]] = {}
    for e in edges:
        if e.predicate != "MENTIONS" or e.object not in date_ids:
            continue
        for span in e.source_spans:
            by_doc.setdefault(span.doc_id, []).append(
                _DateMention(span.doc_id, span.start, span.end, names.get(e.object, ""))
            )
    for doc_id in by_doc:
        by_doc[doc_id].sort(key=lambda d: (d.start, d.end, d.name))
    return by_doc


def _nearest_date(span: SourceSpan, dates: list[_DateMention]) -> str | None:
    """Nearest in-window Date name to ``span`` (ties: earliest start, then name)."""
    best: tuple[int, int, str] | None = None
    for d in dates:
        if d.end < span.start - _DATE_WINDOW or d.start > span.end + _DATE_WINDOW:
            continue
        if d.start <= span.end and d.end >= span.start:
            gap = 0  # overlapping / inside the relation span
        else:
            gap = min(abs(d.start - span.end), abs(span.start - d.end))
        cand = (gap, d.start, d.name)
        if best is None or cand < best:
            best = cand
    return best[2] if best is not None else None


def _reified_edge(
    subject: str,
    predicate: str,
    obj: str,
    src: Edge,
) -> Edge:
    """A structural link between an entity and its Claim, re-citing the relation span."""
    span = src.source_spans[0] if src.source_spans else None
    span_key = f"{span.doc_id}|{span.start}|{span.end}" if span else "nospan"
    return Edge(
        edge_id="edge:" + hash_text(f"{subject}|{predicate}|{obj}|{span_key}"),
        subject=subject,
        predicate=predicate,
        object=obj,
        tag=ConfidenceTag.INFERRED,
        confidence=src.confidence,
        evidence_count=src.evidence_count,
        source_spans=src.source_spans,
        properties={},
    )


def reify_claims(nodes: list[Node], edges: list[Edge]) -> tuple[list[Node], list[Edge]]:
    """Reify every entity-to-entity relation edge into a Claim node + link edges.

    Returns ``(claim_nodes, claim_edges)``. For each relation edge we emit one
    ``Claim`` node and two INFERRED links: ``subject -[SUBJECT_OF]-> claim`` and
    ``claim -[HAS_OBJECT]-> object``. The caller merges these into the graph; the
    original relation edge is left in place.
    """
    entity_ids = frozenset(n.node_id for n in nodes if "Entity" in n.labels)
    dates_by_doc = _date_mentions(nodes, edges)

    claim_nodes: dict[str, Node] = {}
    claim_edges: dict[str, Edge] = {}
    for e in sorted(edges, key=lambda e: e.edge_id):
        if not is_relation_edge(e, entity_ids):
            continue
        cid = claim_id_for(e)
        span = e.source_spans[0] if e.source_spans else None
        t_valid = (
            _nearest_date(span, dates_by_doc.get(span.doc_id, [])) if span is not None else None
        )
        props: dict[str, object] = {
            "name": f"{e.subject} {e.predicate} {e.object}",
            "subject": e.subject,
            "predicate": e.predicate,
            "object": e.object,
            "confidence": e.confidence,
            "polarity": e.properties.get("polarity", "pos"),
            "modality": e.properties.get("modality", "asserted"),
            "tag": str(e.tag),
            "evidence_count": e.evidence_count,
            "t_valid": t_valid,
            "t_invalid": None,
        }
        if e.properties.get("amount"):
            props["amount"] = e.properties["amount"]
        claim_nodes.setdefault(cid, Node(node_id=cid, labels=("Claim",), properties=props))
        s_edge = _reified_edge(e.subject, "SUBJECT_OF", cid, e)
        o_edge = _reified_edge(cid, "HAS_OBJECT", e.object, e)
        claim_edges.setdefault(s_edge.edge_id, s_edge)
        claim_edges.setdefault(o_edge.edge_id, o_edge)

    nodes_out = sorted(claim_nodes.values(), key=lambda n: n.node_id)
    edges_out = sorted(claim_edges.values(), key=lambda e: e.edge_id)
    return nodes_out, edges_out
