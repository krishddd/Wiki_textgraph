"""Emit Chunk nodes + the entity<->chunk links of the dual-node retrieval graph (L8).

HippoRAG-style retrieval routes between two node kinds: passages (``Chunk``) and the
entities they mention. This module materialises that second kind. Each L0 chunk
becomes a ``Chunk`` node carrying its text (so BM25 and citation both read straight
from the graph), linked from its document by ``HAS_CHUNK``; every entity mention that
falls inside a chunk's byte range yields a ``chunk -[MENTIONS]-> entity`` edge, which
is what lets a lexical hit on a passage teleport PageRank onto the right entities.

Chunk-membership is computed by containment of the entity's raw-byte mention span in
the chunk's raw-byte range, so every emitted edge cites real bytes and re-verifies
(G3). Deterministic throughout (G1).
"""

from __future__ import annotations

from textgraph.core.content_address import hash_text
from textgraph.core.layout import IngestResult
from textgraph.l1_structure.emit import sanitize, source_span
from textgraph.store.base import ConfidenceTag, Edge, Node, SourceSpan

_HAS_CHUNK_CONF = 1.0
_MENTIONS_CONF = 0.9


def _chunk_node(
    ir: IngestResult,
    chunk_id: str,
    text: str,
    breadcrumb: tuple[str, ...],
    token_count: int,
    index: int,
    layout_type: str,
) -> Node:
    return Node(
        node_id=chunk_id,
        labels=("Chunk",),
        properties={
            "name": sanitize(text[:80]),
            "text": sanitize(text),
            "doc_id": ir.doc_id,
            "breadcrumb": [sanitize(b) for b in breadcrumb],
            "token_count": token_count,
            "index": index,
            "layout_type": str(layout_type),
        },
    )


def emit_chunks(
    results: list[IngestResult], nodes: list[Node], edges: list[Edge]
) -> tuple[list[Node], list[Edge]]:
    """Return ``(chunk_nodes, chunk_edges)`` for the dual-node retrieval graph."""
    entity_ids = {n.node_id for n in nodes if "Entity" in n.labels}

    # doc_id -> [(raw_start, raw_end, chunk_id)], sorted, for containment lookup.
    chunk_ranges: dict[str, list[tuple[int, int, str]]] = {}
    chunk_nodes: list[Node] = []
    chunk_edges: dict[str, Edge] = {}

    for ir in results:
        for ch in ir.chunks:
            chunk_nodes.append(
                _chunk_node(
                    ir,
                    ch.chunk_id,
                    ch.text,
                    ch.breadcrumb,
                    ch.token_count,
                    ch.index,
                    str(ch.layout_type),
                )
            )
            b0, b1 = ir.canonical.raw_span(ch.span.start, ch.span.end)
            chunk_ranges.setdefault(ir.doc_id, []).append((b0, b1, ch.chunk_id))
            span = source_span(ir, ch.span)
            has_chunk = Edge(
                edge_id="edge:" + hash_text(f"doc:{ir.doc_id}|HAS_CHUNK|{ch.chunk_id}"),
                subject=f"doc:{ir.doc_id}",
                predicate="HAS_CHUNK",
                object=ch.chunk_id,
                tag=ConfidenceTag.STRUCTURAL,
                confidence=_HAS_CHUNK_CONF,
                evidence_count=1,
                source_spans=(span,),
                properties={},
            )
            chunk_edges.setdefault(has_chunk.edge_id, has_chunk)
    for doc_id in chunk_ranges:
        chunk_ranges[doc_id].sort()

    # Entity mentions come from the aggregated doc->entity MENTIONS edges (they carry
    # every occurrence's raw byte span). Attribute each mention to its containing chunk.
    for e in edges:
        if e.predicate != "MENTIONS" or e.object not in entity_ids:
            continue
        for span in e.source_spans:
            chunk_id = _containing_chunk(chunk_ranges.get(span.doc_id, []), span)
            if chunk_id is None:
                continue
            edge = Edge(
                edge_id="edge:" + hash_text(f"{chunk_id}|MENTIONS|{e.object}"),
                subject=chunk_id,
                predicate="MENTIONS",
                object=e.object,
                tag=ConfidenceTag.INFERRED,
                confidence=_MENTIONS_CONF,
                evidence_count=1,
                source_spans=(span,),
                properties={},
            )
            existing = chunk_edges.get(edge.edge_id)
            if existing is None:
                chunk_edges[edge.edge_id] = edge
            else:
                # Same entity mentioned several times in one chunk: accumulate spans.
                chunk_edges[edge.edge_id] = Edge(
                    edge_id=existing.edge_id,
                    subject=existing.subject,
                    predicate=existing.predicate,
                    object=existing.object,
                    tag=existing.tag,
                    confidence=existing.confidence,
                    evidence_count=existing.evidence_count + 1,
                    source_spans=(*existing.source_spans, span),
                    properties=existing.properties,
                )

    nodes_out = sorted(chunk_nodes, key=lambda n: n.node_id)
    edges_out = sorted(chunk_edges.values(), key=lambda e: e.edge_id)
    return nodes_out, edges_out


def _containing_chunk(ranges: list[tuple[int, int, str]], span: SourceSpan) -> str | None:
    """Smallest chunk whose raw byte range contains ``span`` (deterministic)."""
    best: tuple[int, str] | None = None
    for b0, b1, chunk_id in ranges:
        if b0 <= span.start and span.end <= b1:
            size = b1 - b0
            cand = (size, chunk_id)
            if best is None or cand < best:
                best = cand
    return best[1] if best is not None else None
