"""Persistent DuckDB-backed :class:`GraphStore` (behind the ``[graph]``/``[er]`` extra).

The in-memory store is rebuilt from scratch every run; this backend serializes an
assembled graph to a DuckDB file so it can be **reloaded from disk without re-running
the pipeline** — the storage half of incrementality (G5) and the on-disk tier of the
tech-stack plan. ``duckdb`` is imported lazily and guarded, so importing this module
never fails in CI; :func:`load_graph` / :func:`persist` raise a clear
:class:`UnsupportedFormat` when the extra is absent.

Round-trip is exact: labels/properties/spans are stored as JSON and the confidence
tag as its enum value, so ``load_graph(persist(nodes, edges))`` returns byte-equal
:class:`Node` / :class:`Edge` objects. Reads are deterministically ordered by id (G1).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from textgraph.l0_ingest.base import UnsupportedFormat
from textgraph.store.base import ConfidenceTag, Edge, GraphStore, Node, SourceSpan

_NODES_DDL = (
    "CREATE TABLE IF NOT EXISTS nodes (node_id VARCHAR PRIMARY KEY, labels VARCHAR, props VARCHAR)"
)
_EDGES_DDL = (
    "CREATE TABLE IF NOT EXISTS edges ("
    "edge_id VARCHAR PRIMARY KEY, subject VARCHAR, predicate VARCHAR, object VARCHAR, "
    "tag VARCHAR, confidence DOUBLE, evidence_count BIGINT, spans VARCHAR, props VARCHAR)"
)


def _require_duckdb() -> Any:
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - exercised only without [graph]
        raise UnsupportedFormat(
            "DuckDB storage requires the [graph] (or [er]) extra: pip install 'textgraph[graph]'"
        ) from exc
    return duckdb


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _node_row(n: Node) -> list[Any]:
    return [n.node_id, _dumps(list(n.labels)), _dumps(n.properties)]


def _edge_row(e: Edge) -> list[Any]:
    spans = [
        {
            "doc_id": s.doc_id,
            "start": s.start,
            "end": s.end,
            "hash": s.hash,
            **({"page": s.page} if s.page else {}),
        }
        for s in e.source_spans
    ]
    return [
        e.edge_id,
        e.subject,
        e.predicate,
        e.object,
        str(e.tag),
        float(e.confidence),
        int(e.evidence_count),
        _dumps(spans),
        _dumps(e.properties),
    ]


def _row_to_node(row: tuple[Any, ...]) -> Node:
    return Node(node_id=row[0], labels=tuple(json.loads(row[1])), properties=json.loads(row[2]))


def _row_to_edge(row: tuple[Any, ...]) -> Edge:
    spans = tuple(
        SourceSpan(
            doc_id=s["doc_id"],
            start=s["start"],
            end=s["end"],
            hash=s["hash"],
            page=int(s.get("page", 0)),
        )
        for s in json.loads(row[7])
    )
    return Edge(
        edge_id=row[0],
        subject=row[1],
        predicate=row[2],
        object=row[3],
        tag=ConfidenceTag(row[4]),
        confidence=float(row[5]),
        evidence_count=int(row[6]),
        source_spans=spans,
        properties=json.loads(row[8]),
    )


class DuckDBGraphStore(GraphStore):
    """A :class:`GraphStore` backed by a DuckDB database file on disk."""

    def __init__(self, path: str | Path) -> None:
        duckdb = _require_duckdb()
        self._con = duckdb.connect(str(path))
        self._con.execute(_NODES_DDL)
        self._con.execute(_EDGES_DDL)

    # -- GraphStore interface ---------------------------------------------------

    def add_node(self, node: Node) -> None:
        self._con.execute("INSERT OR REPLACE INTO nodes VALUES (?, ?, ?)", _node_row(node))

    def add_edge(self, edge: Edge) -> None:
        self._con.execute(
            "INSERT OR REPLACE INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", _edge_row(edge)
        )

    def get_node(self, node_id: str) -> Node | None:
        row = self._con.execute(
            "SELECT node_id, labels, props FROM nodes WHERE node_id = ?", [node_id]
        ).fetchone()
        return _row_to_node(row) if row else None

    def neighbors(self, node_id: str) -> list[Edge]:
        rows = self._con.execute(
            "SELECT edge_id, subject, predicate, object, tag, confidence, evidence_count, "
            "spans, props FROM edges WHERE subject = ? ORDER BY edge_id",
            [node_id],
        ).fetchall()
        return [_row_to_edge(r) for r in rows]

    def nodes(self) -> list[Node]:
        rows = self._con.execute(
            "SELECT node_id, labels, props FROM nodes ORDER BY node_id"
        ).fetchall()
        return [_row_to_node(r) for r in rows]

    def edges(self) -> list[Edge]:
        rows = self._con.execute(
            "SELECT edge_id, subject, predicate, object, tag, confidence, evidence_count, "
            "spans, props FROM edges ORDER BY edge_id"
        ).fetchall()
        return [_row_to_edge(r) for r in rows]

    # -- snapshot helpers -------------------------------------------------------

    def replace_all(self, nodes: list[Node], edges: list[Edge]) -> None:
        """Overwrite the store with a fresh snapshot (used by :func:`persist`)."""
        self._con.execute("DELETE FROM nodes")
        self._con.execute("DELETE FROM edges")
        if nodes:
            self._con.executemany(
                "INSERT INTO nodes VALUES (?, ?, ?)", [_node_row(n) for n in nodes]
            )
        if edges:
            self._con.executemany(
                "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [_edge_row(e) for e in edges],
            )

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> DuckDBGraphStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def persist(path: str | Path, nodes: list[Node], edges: list[Edge]) -> Path:
    """Write ``(nodes, edges)`` to a DuckDB file at ``path`` and return the path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBGraphStore(p) as store:
        store.replace_all(nodes, edges)
    return p


def load_graph(path: str | Path) -> tuple[list[Node], list[Edge]]:
    """Load ``(nodes, edges)`` from a DuckDB file — no pipeline rebuild (G5)."""
    with DuckDBGraphStore(path) as store:
        return store.nodes(), store.edges()
