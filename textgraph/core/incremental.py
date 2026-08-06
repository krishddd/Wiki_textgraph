"""Content-addressed incremental cache for per-document IE (G5).

The costly layer is per-document encoder IE (L2/L3); it is a pure function of the
document's bytes and the pinned config. This cache stores each document's emitted IE
nodes/edges (plus its coref/relation counts) keyed by ``(doc_id, config_hash)`` — the
doc_id already *is* the blake3 of the raw bytes, so an edit changes the key and only
the changed file is re-extracted. Everything is stored as exact Node/Edge JSON, so an
incremental build is **byte-identical** to a full build (G1); the cross-document
layers (L5 through L8) always re-run over the merged set.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

from textgraph.store.base import ConfidenceTag, Edge, Node, SourceSpan


def node_to_dict(n: Node) -> dict[str, Any]:
    return {"node_id": n.node_id, "labels": list(n.labels), "properties": n.properties}


def node_from_dict(d: dict[str, Any]) -> Node:
    return Node(node_id=d["node_id"], labels=tuple(d["labels"]), properties=d["properties"])


def edge_to_dict(e: Edge) -> dict[str, Any]:
    return {
        "edge_id": e.edge_id,
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


def edge_from_dict(d: dict[str, Any]) -> Edge:
    return Edge(
        edge_id=d["edge_id"],
        subject=d["subject"],
        predicate=d["predicate"],
        object=d["object"],
        tag=ConfidenceTag(d["tag"]),
        confidence=float(d["confidence"]),
        evidence_count=int(d["evidence_count"]),
        source_spans=tuple(
            SourceSpan(doc_id=s["doc_id"], start=s["start"], end=s["end"], hash=s["hash"])
            for s in d["source_spans"]
        ),
        properties=d["properties"],
    )


class DocIECache:
    """Per-document IE cache on disk, keyed by ``(doc_id, config_hash)``."""

    def __init__(self, cache_dir: str | Path) -> None:
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    def _path(self, doc_id: str, config_hash: str) -> Path:
        # doc_id is "blake3:<hex>"; keep the hex + a config-hash prefix in the filename.
        safe = doc_id.replace(":", "_")
        return self.dir / f"{safe}.{config_hash[:12]}.json"

    def get(self, doc_id: str, config_hash: str) -> dict[str, Any] | None:
        p = self._path(doc_id, config_hash)
        if not p.exists():
            self.misses += 1
            return None
        try:
            payload: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
            entry = {
                "nodes": [node_from_dict(n) for n in payload["nodes"]],
                "edges": [edge_from_dict(e) for e in payload["edges"]],
                "pronouns_total": payload.get("pronouns_total", 0),
                "pronouns_resolved": payload.get("pronouns_resolved", 0),
                "relations": payload.get("relations", 0),
            }
        except (ValueError, KeyError, TypeError, OSError):
            # A corrupt / partially-written cache entry (crash mid-write, truncated JSON) is
            # treated as a miss and re-extracted, so a bad cache never fails a build (G5).
            self.misses += 1
            with contextlib.suppress(OSError):
                p.unlink()  # drop the poisoned entry so the fresh result can replace it
            return None
        self.hits += 1
        return entry

    def put(
        self,
        doc_id: str,
        config_hash: str,
        nodes: list[Node],
        edges: list[Edge],
        *,
        pronouns_total: int,
        pronouns_resolved: int,
        relations: int,
    ) -> None:
        payload = {
            "nodes": [node_to_dict(n) for n in nodes],
            "edges": [edge_to_dict(e) for e in edges],
            "pronouns_total": pronouns_total,
            "pronouns_resolved": pronouns_resolved,
            "relations": relations,
        }
        self._path(doc_id, config_hash).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
