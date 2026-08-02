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

    t1 = time.perf_counter()
    nodes, edges = parse_corpus(results)
    l1_ms = (time.perf_counter() - t1) * 1000

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
        timings_ms={"L0": l0_ms, "L1": l1_ms},
        skipped=skipped,
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
