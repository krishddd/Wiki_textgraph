"""Helpers for emitting L1 graph elements with re-verifiable provenance (G3, G4).

Every L1 edge is ``STRUCTURAL`` with ``confidence = 1.0`` and a source span whose
hash is computed from the exact raw bytes, so the provenance-integrity gate can
re-hash it. Node and edge ids are content-addressed for determinism (G1).
"""

from __future__ import annotations

import re

from textgraph.core.content_address import blake3_hex, hash_text
from textgraph.core.layout import IngestResult, Span
from textgraph.store.base import ConfidenceTag, Edge, Node, SourceSpan

_NORMALIZE = re.compile(r"\s+")


def sanitize(text: str) -> str:
    """Replace lone surrogates with U+FFFD so display strings are valid Unicode.

    Provenance is unaffected — source spans always cite raw bytes, never this
    display text — but node names / properties must serialize cleanly to graph.json.
    """
    if not any("\ud800" <= ch <= "\udfff" for ch in text):
        return text
    return "".join("�" if "\ud800" <= ch <= "\udfff" else ch for ch in text)


def _clean_props(props: dict[str, object]) -> dict[str, object]:
    return {k: sanitize(v) if isinstance(v, str) else v for k, v in props.items()}


def normalize_key(text: str) -> str:
    """Lowercased, whitespace-collapsed, surrogate-safe key for canonical ids."""
    return _NORMALIZE.sub(" ", sanitize(text)).strip().lower()


def source_span(ir: IngestResult, span: Span) -> SourceSpan:
    """Build a re-verifiable :class:`SourceSpan` from a canonical-char span.

    Stamps the 1-based page (from the doc's page map) and the block bounding box (from the
    doc's bbox map) when the source is paged; 0/None otherwise. Additive only — the byte range
    is what re-verification checks, page and bbox are metadata.
    """
    b0, b1 = ir.canonical.raw_span(span.start, span.end)
    return SourceSpan(
        doc_id=ir.doc_id,
        start=b0,
        end=b1,
        hash=blake3_hex(ir.raw[b0:b1]),
        page=ir.page_for(span.start),
        bbox=ir.bbox_for(span.start),
    )


def node(node_id: str, label: str, name: str, **props: object) -> Node:
    return Node(
        node_id=node_id,
        labels=(label,),
        properties={"name": sanitize(name), **_clean_props(props)},
    )


def edge(
    subject: str,
    predicate: str,
    obj: str,
    span: SourceSpan,
    *,
    tag: ConfidenceTag = ConfidenceTag.STRUCTURAL,
    confidence: float = 1.0,
    **props: object,
) -> Edge:
    edge_id = "edge:" + hash_text(
        f"{subject}|{predicate}|{obj}|{span.doc_id}|{span.start}|{span.end}"
    )
    return Edge(
        edge_id=edge_id,
        subject=subject,
        predicate=predicate,
        object=obj,
        tag=tag,
        confidence=confidence,
        evidence_count=1,
        source_spans=(span,),
        properties=_clean_props(dict(props)),
    )
