"""Emit L5 resolution as canonical nodes + non-destructive SAME_AS edges.

Original entity nodes are untouched; a new ``("Entity","Canonical",<etype>)`` node
represents the resolved identity, and each member links to it via a ``SAME_AS`` edge
tagged INFERRED (an engine-derived merge) with the member's mention span as evidence
(G3) — so the merge is auditable and fully reversible (§8.3).
"""

from __future__ import annotations

from textgraph.core.content_address import hash_text
from textgraph.l1_structure.emit import sanitize
from textgraph.l5_entity_resolution.model import ERResult
from textgraph.store.base import ConfidenceTag, Edge, Node


def emit_er(er: ERResult) -> tuple[list[Node], list[Edge]]:
    nodes: list[Node] = []
    edges: list[Edge] = []

    for c in er.clusters:
        nodes.append(
            Node(
                node_id=c.canonical_id,
                labels=("Entity", "Canonical", c.etype),
                properties={
                    "name": sanitize(c.canonical_name),
                    "etype": c.etype,
                    "member_count": len(c.members),
                },
            )
        )
    for sa in er.same_as:
        edges.append(
            Edge(
                edge_id="edge:" + hash_text(f"{sa.member_id}|SAME_AS|{sa.canonical_id}"),
                subject=sa.member_id,
                predicate="SAME_AS",
                object=sa.canonical_id,
                tag=ConfidenceTag.INFERRED,
                confidence=sa.score,
                evidence_count=1,
                source_spans=(sa.source,),
                properties={},
            )
        )
    return nodes, edges
