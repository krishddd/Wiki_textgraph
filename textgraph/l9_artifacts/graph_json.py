"""graph.json serialization (L9) — the agent's contract.

Canonical, versioned, byte-stable (G1). Arrays are sorted by stable key and object
keys are canonical-sorted at write time. Conforms to schema/graph.schema.json.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from textgraph import __version__
from textgraph.core.canonical_json import canonical_dump_bytes
from textgraph.core.layout import IngestResult
from textgraph.store.base import Edge, Node

SCHEMA_VERSION = "1.0"


def _node_dict(n: Node) -> dict[str, Any]:
    return {
        "node_id": n.node_id,
        "labels": list(n.labels),
        "properties": n.properties,
    }


def _edge_dict(e: Edge) -> dict[str, Any]:
    return {
        "subject": e.subject,
        "predicate": e.predicate,
        "object": e.object,
        "tag": str(e.tag),
        "confidence": e.confidence,
        "evidence_count": e.evidence_count,
        "source_spans": [
            {"doc_id": s.doc_id, "start": s.start, "end": s.end, "hash": s.hash}
            for s in e.source_spans
        ],
        "properties": e.properties,
    }


def build_graph_document(
    *,
    config_hash: str,
    results: list[IngestResult],
    nodes: list[Node],
    edges: list[Edge],
) -> dict[str, Any]:
    """Assemble the full graph.json document (a plain dict, ready to serialize)."""
    docs = sorted(
        (
            {
                "doc_id": ir.doc_id,
                "source_name": ir.source_name,
                "path": ir.source_path,
                "format": ir.format,
                "lang": ir.lang,
                "raw_len": ir.canonical.raw_len,
                "text_len": len(ir.text),
                "chunk_count": len(ir.chunks),
            }
            for ir in results
        ),
        key=lambda d: (d["doc_id"], d["source_name"]),
    )
    tag_counts = Counter(str(e.tag) for e in edges)
    node_dicts = sorted((_node_dict(n) for n in nodes), key=lambda d: d["node_id"])
    edge_dicts = sorted(
        (_edge_dict(e) for e in edges),
        key=lambda d: (d["subject"], d["predicate"], d["object"], str(d["source_spans"])),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": __version__,
        "config_hash": config_hash,
        "stats": {
            "doc_count": len(docs),
            "node_count": len(node_dicts),
            "edge_count": len(edge_dicts),
            "total_raw_bytes": sum(d["raw_len"] for d in docs),
            "tag_counts": dict(sorted(tag_counts.items())),
        },
        "docs": docs,
        "nodes": node_dicts,
        "edges": edge_dicts,
    }


def dump_graph_bytes(document: dict[str, Any]) -> bytes:
    return canonical_dump_bytes(document)
