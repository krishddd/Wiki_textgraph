"""Co-occurrence backbone (opt-in) — STRUCTURAL edges between co-mentioned entities.

Prose corpora routinely *name* many entities while stating few explicit relations. The
deterministic extractors are precise, so such a build yields a graph that is mostly
orphans: analytics find no communities, the force layout has nothing to pull together,
and the viewer shows a dust of unconnected dots. This module derives an honest,
deterministic connective tissue: two entities mentioned in the **same chunk** are
co-mentioned, and a ``CO_OCCURS`` edge records that, cited by the shared chunk's byte
span (G3) so it re-verifies like any other edge.

Unlike the console's view-only fallback (``l8_retrieval.engine._cooccurrence_edges``),
these are real graph edges: emitted before L5/L7, they flow through entity resolution,
PageRank, community detection and layout. They are tagged ``STRUCTURAL`` (not a claim
about *how* the entities relate, only that they co-occur) and are **opt-in**
(``Config.co_occurrence``), so the baseline determinism gate is untouched.

Bounded for large chunks (G7): a small chunk contributes every pair; a large one links
hub-and-spoke to its lexically-first member, guaranteeing connectivity without a
hairball. Pure function of ``(results, nodes, edges)`` — deterministic throughout (G1).
"""

from __future__ import annotations

from itertools import combinations

from textgraph.core.content_address import hash_text
from textgraph.core.layout import IngestResult
from textgraph.l1_structure.emit import source_span
from textgraph.store.base import ConfidenceTag, Edge, Node, SourceSpan

# A chunk denser than this is boilerplate (a table, an index) — every pair would be noise.
_MAX_CHUNK_ENTITIES = 40
# All-pairs below this; hub-and-spoke above it, to keep the edge count O(entities).
_ALL_PAIRS_THRESHOLD = 8


def _containing_chunk(ranges: list[tuple[int, int, str]], span: SourceSpan) -> str | None:
    """Smallest chunk whose raw byte range contains ``span`` (deterministic)."""
    best: tuple[int, str] | None = None
    for b0, b1, chunk_id in ranges:
        if b0 <= span.start and span.end <= b1:
            cand = (b1 - b0, chunk_id)
            if best is None or cand < best:
                best = cand
    return best[1] if best is not None else None


def cooccurrence_edges(
    results: list[IngestResult], nodes: list[Node], edges: list[Edge]
) -> list[Edge]:
    """Return ``CO_OCCURS`` edges among entities that share a chunk (STRUCTURAL, cited).

    Membership reuses the byte-containment logic of L8 chunk emission: each doc->entity
    ``MENTIONS`` occurrence is attributed to its smallest containing chunk. The emitted
    edge cites that chunk's span, so provenance re-verifies.
    """
    entity_ids = {n.node_id for n in nodes if "Entity" in n.labels}

    # doc_id -> sorted [(raw_start, raw_end, chunk_id)] and chunk_id -> its citable span.
    chunk_ranges: dict[str, list[tuple[int, int, str]]] = {}
    chunk_span: dict[str, SourceSpan] = {}
    for ir in results:
        for ch in ir.chunks:
            b0, b1 = ir.canonical.raw_span(ch.span.start, ch.span.end)
            chunk_ranges.setdefault(ir.doc_id, []).append((b0, b1, ch.chunk_id))
            chunk_span[ch.chunk_id] = source_span(ir, ch.span)
    for ranges in chunk_ranges.values():
        ranges.sort()

    # chunk_id -> the set of entities mentioned inside it.
    members: dict[str, set[str]] = {}
    for e in edges:
        if e.predicate != "MENTIONS" or e.object not in entity_ids:
            continue
        for span in e.source_spans:
            cid = _containing_chunk(chunk_ranges.get(span.doc_id, []), span)
            if cid is not None:
                members.setdefault(cid, set()).add(e.object)

    # Count how many chunks each pair shares (evidence strength) and remember one span.
    pair_count: dict[tuple[str, str], int] = {}
    pair_span: dict[tuple[str, str], SourceSpan] = {}

    def _bump(a: str, b: str, span: SourceSpan) -> None:
        key = (a, b) if a < b else (b, a)
        pair_count[key] = pair_count.get(key, 0) + 1
        pair_span.setdefault(key, span)

    for cid in sorted(members):
        group = sorted(members[cid])
        if not 2 <= len(group) <= _MAX_CHUNK_ENTITIES:
            continue
        span = chunk_span[cid]
        if len(group) <= _ALL_PAIRS_THRESHOLD:
            for a, b in combinations(group, 2):
                _bump(a, b, span)
        else:  # hub-and-spoke to the lexically-first member — O(k) edges, still connected
            hub = group[0]
            for other in group[1:]:
                _bump(hub, other, span)

    out: list[Edge] = []
    for (a, b), n in pair_count.items():
        span = pair_span[(a, b)]
        eid = "edge:" + hash_text(f"{a}|CO_OCCURS|{b}")
        out.append(
            Edge(
                edge_id=eid,
                subject=a,
                predicate="CO_OCCURS",
                object=b,
                tag=ConfidenceTag.STRUCTURAL,
                confidence=round(min(1.0, 0.3 + 0.1 * n), 4),
                evidence_count=n,
                source_spans=(span,),
                properties={"basis": "co-mention"},
            )
        )
    return sorted(out, key=lambda e: e.edge_id)
