"""graph.json serialization (L9) — the agent's contract.

Canonical, versioned, byte-stable (G1). Arrays are sorted by stable key and object
keys are canonical-sorted at write time. Conforms to schema/graph.schema.json.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from textgraph import __version__
from textgraph.core.canonical_json import canonical_dump_bytes
from textgraph.core.content_address import hash_text
from textgraph.core.layout import IngestResult
from textgraph.store.base import ConfidenceTag, Edge, Node, SourceSpan

SCHEMA_VERSION = "1.0"


def load_graph_json(path: str | Path) -> tuple[list[Node], list[Edge]]:
    """Reconstruct ``(nodes, edges)`` from a written ``graph.json`` artifact.

    Lets a viewer/engine be built from an *existing* build — including an LLM-enriched one
    (``build --llm-extract``) — without re-running the pipeline. ``graph.json`` doesn't store
    edge ids (they're derived), so a stable content-addressed id is re-synthesised here.
    """
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    nodes = [
        Node(node_id=n["node_id"], labels=tuple(n["labels"]), properties=dict(n["properties"]))
        for n in doc["nodes"]
    ]
    edges: list[Edge] = []
    for e in doc["edges"]:
        spans = tuple(
            SourceSpan(doc_id=s["doc_id"], start=s["start"], end=s["end"], hash=s["hash"])
            for s in e.get("source_spans", [])
        )
        span_key = "|".join(f"{s.doc_id}|{s.start}|{s.end}" for s in spans)
        edge_id = "edge:" + hash_text(f"{e['subject']}|{e['predicate']}|{e['object']}|{span_key}")
        edges.append(
            Edge(
                edge_id=edge_id,
                subject=e["subject"],
                predicate=e["predicate"],
                object=e["object"],
                tag=ConfidenceTag(e["tag"]),
                confidence=float(e["confidence"]),
                evidence_count=int(e.get("evidence_count", 0)),
                source_spans=spans,
                properties=dict(e.get("properties", {})),
            )
        )
    return nodes, edges


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
