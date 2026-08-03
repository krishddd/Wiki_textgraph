"""Emit L3 IE results as graph nodes/edges with confidence tags + provenance.

Entity nodes are labelled ``("Entity", <etype>)``. Mentions become EXTRACTED
``MENTIONS`` edges (doc → entity); typed relations become EXTRACTED edges, or
INFERRED when an endpoint was resolved via coref. Every edge carries a re-verifiable
source span (G3), realising the full four-tier taxonomy (G4).
"""

from __future__ import annotations

from textgraph.core.layout import IngestResult
from textgraph.l1_structure.emit import edge, sanitize, source_span
from textgraph.l3_encoder_ie.model import IEResult
from textgraph.store.base import ConfidenceTag, Edge, Node

_ENTITY_CONF = 0.9
_RELATION_CONF = 0.78
_INFERRED_CONF = 0.6


def emit_ie(ir: IngestResult, ie: IEResult) -> tuple[list[Node], list[Edge]]:
    nodes: list[Node] = []
    edges: list[Edge] = []
    doc_id = f"doc:{ir.doc_id}"

    for eid, ent in sorted(ie.entities.items()):
        nodes.append(
            Node(
                node_id=eid,
                labels=("Entity", ent.etype),
                properties={
                    "name": sanitize(ent.name),
                    "etype": ent.etype,
                    "mention_count": len(ent.mentions),
                },
            )
        )
        for m in ent.mentions:
            edges.append(
                edge(
                    doc_id,
                    "MENTIONS",
                    eid,
                    source_span(ir, m.span),
                    tag=ConfidenceTag.EXTRACTED,
                    confidence=_ENTITY_CONF,
                    etype=ent.etype,
                )
            )

    for r in ie.relations:
        tag = ConfidenceTag.INFERRED if r.inferred else ConfidenceTag.EXTRACTED
        conf = _INFERRED_CONF if r.inferred else _RELATION_CONF
        props: dict[str, object] = {
            "surface_predicate": r.surface,
            "polarity": r.polarity,
            "modality": r.modality,
        }
        if r.amount:
            props["amount"] = r.amount
        edges.append(
            edge(
                r.subject_id,
                r.predicate,
                r.object_id,
                source_span(ir, r.span),
                tag=tag,
                confidence=conf,
                **props,
            )
        )

    return nodes, edges
