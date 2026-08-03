"""TextGraph build pipeline (Phase 1: L0 + L1).

Runs deterministic ingestion (L0) and zero-model structure parsing (L1) over a
corpus, assembles an in-memory graph, and produces the L9 artifacts. Each later
phase slots a real layer in without changing this orchestration or breaking the
byte-identical guarantee (G1).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from textgraph.core.config import Config
from textgraph.core.layout import IngestResult
from textgraph.l0_ingest import ingest_path
from textgraph.l0_ingest.base import UnsupportedFormat
from textgraph.l1_structure import parse_corpus
from textgraph.l3_encoder_ie import emit_ie, run_ie
from textgraph.l9_artifacts.graph_json import build_graph_document, dump_graph_bytes
from textgraph.store.base import Edge, Node
from textgraph.store.memory import InMemoryGraphStore

# Extensions we attempt to ingest. Everything else is skipped so a corpus dir can
# sit next to binaries without polluting the graph. Unknown *text* extensions can
# still be ingested explicitly via the L0 API.
_INGEST_EXTENSIONS = frozenset(
    {
        ".md",
        ".markdown",
        ".mdx",
        ".txt",
        ".text",
        ".log",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".chat",
        ".transcript",
        # Rich documents (investigator formats: filings, memos, reports, exports).
        ".html",
        ".htm",
        ".xhtml",
        ".docx",
        ".odt",
        ".rtf",
        ".epub",
        ".pdf",
    }
)


@dataclass
class BuildResult:
    config: Config
    results: list[IngestResult]
    store: InMemoryGraphStore
    nodes: list[Node]
    edges: list[Edge]
    timings_ms: dict[str, float] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    ie_stats: dict[str, int] = field(default_factory=dict)

    @property
    def config_hash(self) -> str:
        return self.config.config_hash()


def _iter_corpus_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in _INGEST_EXTENSIONS
    )


def build(root: str | Path, *, config: Config | None = None) -> BuildResult:
    """Run L0 + L1 over a corpus path and return the assembled graph."""
    config = config or Config()
    root = Path(root)

    results: list[IngestResult] = []
    skipped: list[str] = []
    t0 = time.perf_counter()
    for p in _iter_corpus_files(root):
        try:
            results.append(ingest_path(p))
        except UnsupportedFormat as exc:
            skipped.append(f"{p.name}: {exc}")
    l0_ms = (time.perf_counter() - t0) * 1000

    # L1 — deterministic structural spine.
    t1 = time.perf_counter()
    nodes, edges = parse_corpus(results)
    l1_ms = (time.perf_counter() - t1) * 1000

    # L2 + L3 — encoder IE (default: deterministic rule backend). Entities merge
    # across documents by (type, normalized name); relations/mentions carry spans.
    entity_nodes: dict[str, Node] = {}
    ie_edges: dict[str, Edge] = {}
    ie_ms = 0.0
    pron_total = pron_resolved = entity_count = relation_count = 0
    if config.extract_ie:
        t2 = time.perf_counter()
        for ir in results:
            ie = run_ie(ir.text, backend=config.ie_backend)
            pron_total += ie.pronouns_total
            pron_resolved += ie.pronouns_resolved
            relation_count += len(ie.relations)
            ie_n, ie_e = emit_ie(ir, ie)
            for n in ie_n:
                entity_nodes.setdefault(n.node_id, n)
            for e in ie_e:
                ie_edges.setdefault(e.edge_id, e)
        entity_count = len(entity_nodes)
        ie_ms = (time.perf_counter() - t2) * 1000

    merged_nodes = {n.node_id: n for n in nodes} | entity_nodes
    merged_edges = {e.edge_id: e for e in edges} | ie_edges
    nodes = sorted(merged_nodes.values(), key=lambda n: n.node_id)
    edges = sorted(merged_edges.values(), key=lambda e: e.edge_id)

    store = InMemoryGraphStore()
    for n in nodes:
        store.add_node(n)
    for e in edges:
        store.add_edge(e)

    return BuildResult(
        config=config,
        results=results,
        store=store,
        nodes=nodes,
        edges=edges,
        timings_ms={"L0": l0_ms, "L1": l1_ms, "L2_L3": ie_ms},
        skipped=skipped,
        ie_stats={
            "entities": entity_count,
            "relations": relation_count,
            "pronouns_total": pron_total,
            "pronouns_resolved": pron_resolved,
        },
    )


def build_graph(root: str | Path, *, config: Config | None = None) -> dict[str, object]:
    """Build and return the graph.json document (dict)."""
    result = build(root, config=config)
    return build_graph_document(
        config_hash=result.config_hash,
        results=result.results,
        nodes=result.nodes,
        edges=result.edges,
    )


def build_graph_bytes(root: str | Path, *, config: Config | None = None) -> bytes:
    """Return the canonical-JSON bytes of graph.json (what lands on disk)."""
    return dump_graph_bytes(build_graph(root, config=config))
