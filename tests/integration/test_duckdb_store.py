"""Phase 5: DuckDB persistent store — exact round-trip, load without rebuild.

The store lives behind the ``[graph]``/``[er]`` extra. The import guard is always
tested; the round-trip runs only when duckdb is installed (skipped in the lean CI env).
"""

from pathlib import Path

import pytest
from textgraph.l0_ingest.base import UnsupportedFormat
from textgraph.pipeline import build
from textgraph.store import duckdb_store

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


def test_load_graph_without_duckdb_raises_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the optional dependency to look absent, regardless of the environment.
    monkeypatch.setattr(duckdb_store, "_require_duckdb", _raise_unsupported)
    with pytest.raises(UnsupportedFormat, match="DuckDB"):
        duckdb_store.load_graph("x.duckdb")


def _raise_unsupported() -> object:
    raise UnsupportedFormat("DuckDB storage requires the [graph] extra")


def test_roundtrip_is_exact_and_loads_without_rebuild(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    result = build(DOCS)
    path = tmp_path / "graph.duckdb"
    duckdb_store.persist(path, result.nodes, result.edges)

    nodes, edges = duckdb_store.load_graph(path)
    assert nodes == result.nodes
    assert edges == result.edges

    # A QueryEngine built from the loaded store answers without touching the corpus.
    from textgraph.l8_retrieval import QueryEngine

    engine = QueryEngine(nodes, edges)
    assert engine.stats().counts["entities"] == sum(1 for n in result.nodes if "Entity" in n.labels)
