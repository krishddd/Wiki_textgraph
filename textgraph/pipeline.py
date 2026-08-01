"""Trivial deterministic pipeline (Phase 0).

This is a placeholder for the real L0->L9 pipeline. It exists so that the
determinism CI gate is real *from day one*: it ingests a corpus with the L0
primitives (content addressing + normalization) and emits a byte-stable
``graph.json``. Each subsequent phase replaces a stub here with a real layer while
the determinism guarantee stays green.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textgraph import __version__
from textgraph.core import CanonicalDoc, Config, canonical_dump_bytes


def _iter_corpus_files(root: Path) -> list[Path]:
    """Return corpus files in a deterministic, sorted order (G1)."""
    if root.is_file():
        return [root]
    return sorted(p for p in root.rglob("*") if p.is_file())


def build_graph(root: str | Path, *, config: Config | None = None) -> dict[str, Any]:
    """Build a (currently trivial) graph dict from a corpus path.

    Deterministic: same corpus + same config => identical dict => identical
    ``graph.json`` bytes. Documents and their derived facts are emitted in sorted
    order so array ordering is stable.
    """
    config = config or Config()
    root = Path(root)

    docs: list[dict[str, Any]] = []
    for path in _iter_corpus_files(root):
        raw = path.read_bytes()
        doc = CanonicalDoc.from_bytes(raw, source_name=path.name)
        docs.append(
            {
                "doc_id": doc.doc_id,
                "source_name": doc.source_name,
                "raw_len": doc.raw_len,
                "text_len": len(doc.text),
                "offset_runs": len(doc.offset_map.runs),
            }
        )

    docs.sort(key=lambda d: (d["doc_id"], d["source_name"] or ""))

    return {
        "schema_version": "0.0.1",
        "tool_version": __version__,
        "config_hash": config.config_hash(),
        "stats": {
            "doc_count": len(docs),
            "total_raw_bytes": sum(d["raw_len"] for d in docs),
        },
        "docs": docs,
        # Real nodes/edges arrive with L1 in Phase 1.
        "nodes": [],
        "edges": [],
    }


def build_graph_bytes(root: str | Path, *, config: Config | None = None) -> bytes:
    """Return the canonical-JSON bytes of the built graph (what lands on disk)."""
    return canonical_dump_bytes(build_graph(root, config=config))
