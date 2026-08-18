"""Jupyter integration — the graph in a notebook, with citations intact.

Analysts who live in notebooks shouldn't have to switch to a browser console. This gives them
the graph inline and its answers as DataFrames:

    from textgraph.notebook import TextGraph
    tg = TextGraph("./case-files")     # build a corpus (or load a graph.json / .duckdb)
    tg.show()                          # the interactive canvas, rendered in the cell
    tg.search("who moved the money")   # -> a DataFrame, one [doc:start-end] citation per row
    tg.roles("Acme Corp")              # -> structurally similar entities
    tg.contradictions()               # -> contested claims + a resolution hint

Every query method returns a **citation-bearing** table: the same bounded, cited results the CLI
and MCP tools give, as a ``pandas.DataFrame`` when pandas is present (the ``[notebook]`` extra),
or a plain list of dicts otherwise. Read-only: nothing here writes ``graph.json``.

``pandas`` and ``IPython`` are optional and import-guarded, so importing this module never breaks
the lean core install — the methods degrade to lists / an HTML string when they're absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textgraph.l8_retrieval import QueryEngine
from textgraph.l8_retrieval.model import Citation

_PLUMBING = frozenset(
    {"MENTIONS", "HAS_CHUNK", "SUBJECT_OF", "HAS_OBJECT", "CONTAINS", "SAME_AS", "CONTRADICTS"}
)


def _load(source: str | Path) -> tuple[list[Any], list[Any], str]:
    """Load ``(nodes, edges, config_hash)`` from a corpus dir, graph.json, or .duckdb."""
    path = Path(source)
    if path.is_file() and path.suffix == ".json":
        from textgraph.l9_artifacts.graph_json import load_graph_json

        n, e = load_graph_json(path)
        return n, e, "loaded"
    if path.is_dir() and (path / "graph.json").is_file():
        from textgraph.l9_artifacts.graph_json import load_graph_json

        n, e = load_graph_json(path / "graph.json")
        return n, e, "loaded"
    if path.is_file() and path.suffix == ".duckdb":
        from textgraph.store.duckdb_store import load_graph

        n, e = load_graph(path)
        return n, e, "loaded"
    from textgraph.pipeline import build

    r = build(path)
    return r.nodes, r.edges, r.config_hash


def _cite_str(citations: list[dict[str, Any]] | list[Citation]) -> str:
    """Render a list of citations as a compact ``[doc:start-end]`` string."""
    out = []
    for c in citations:
        if isinstance(c, Citation):
            out.append(c.ref())
        else:
            out.append(f"[{c['doc_id']}:{c['start']}-{c['end']}]")
    return " ".join(out)


class TextGraph:
    """A notebook-friendly handle over a built/loaded graph."""

    def __init__(self, source: str | Path) -> None:
        self._nodes, self._edges, self.config_hash = _load(source)
        self.engine = QueryEngine(self._nodes, self._edges)
        self.source = str(source)

    @classmethod
    def from_engine(cls, engine: QueryEngine) -> TextGraph:
        """Wrap an existing engine (e.g. from ``pipeline.build``) without reloading."""
        self = cls.__new__(cls)
        self.engine = engine
        self._nodes = list(engine._node.values())
        self._edges = engine._edges
        self.config_hash = "engine"
        self.source = "<engine>"
        return self

    # -- inline rendering -----------------------------------------------------------------

    def _graph_html(self) -> str:
        from textgraph.l9_artifacts.analytics_lite import compute
        from textgraph.l9_artifacts.graph_html import build_html

        return build_html(
            results=[],
            nodes=self._nodes,
            edges=self._edges,
            diag=compute(self._nodes, self._edges),
            config_hash=self.config_hash if self.config_hash != "loaded" else "notebook",
        )

    def show(self, *, height: int = 620) -> Any:
        """Render the interactive graph canvas inline in the notebook cell.

        Uses the same self-contained offline viewer as ``graph.html`` (no server, no CDN),
        embedded in a sandboxed iframe. Returns an ``IPython.display.HTML`` when IPython is
        present; otherwise returns the raw HTML string.
        """
        srcdoc = self._graph_html().replace("&", "&amp;").replace('"', "&quot;")
        iframe = (
            f'<iframe srcdoc="{srcdoc}" style="width:100%;height:{int(height)}px;'
            'border:1px solid #e6e7ec;border-radius:10px;" '
            'sandbox="allow-scripts allow-same-origin"></iframe>'
        )
        try:
            from IPython.display import HTML

            return HTML(iframe)
        except ImportError:
            return iframe

    def _repr_html_(self) -> str:
        """A compact summary card so ``tg`` renders inline without drawing the whole graph."""
        gv = self.engine.graph_view()
        ents = len(self.engine._entity_ids)
        rels = sum(1 for e in self._edges if e.predicate not in _PLUMBING)
        comms = len(gv.get("communities", []))
        return (
            '<div style="font:14px system-ui;border:1px solid #e6e7ec;border-radius:10px;'
            'padding:12px 16px;display:inline-block">'
            "<b>TextGraph</b> &middot; "
            f"{ents} entities &middot; {rels} relations &middot; {comms} communities<br>"
            '<span style="color:#8a8d98">'
            f"source: {self.source} &middot; call <code>.show()</code> for the graph"
            "</span></div>"
        )

    # -- citation-bearing tables ----------------------------------------------------------

    def _frame(self, rows: list[dict[str, Any]]) -> Any:
        """A DataFrame when pandas is available, else the list of dicts unchanged."""
        try:
            import pandas as pd

            return pd.DataFrame(rows)
        except ImportError:
            return rows

    def search(self, query: str, *, k: int = 5) -> Any:
        res = self.engine.search(query, k=k).to_dict()
        rows = [
            {
                "rank": i,
                "kind": h["kind"],
                "name": h["name"],
                "score": h["score"],
                "snippet": (h.get("snippet") or "")[:200],
                "citations": _cite_str(h["citations"]),
            }
            for i, h in enumerate(res["hits"], 1)
        ]
        return self._frame(rows)

    def entities(self) -> Any:
        rows = [
            {
                "name": n["name"],
                "type": n.get("etype", ""),
                "pagerank": n.get("pagerank", 0.0),
                "community": n.get("community_label", ""),
                "contradictions": n.get("contradictions", 0),
            }
            for n in self.engine.graph_view()["nodes"]
        ]
        return self._frame(rows)

    def relations(self) -> Any:
        name = {n.node_id: str(n.properties.get("name", n.node_id)) for n in self._nodes}
        rows = [
            {
                "source": name.get(e.subject, e.subject),
                "predicate": e.predicate,
                "target": name.get(e.object, e.object),
                "tag": str(e.tag),
                "confidence": round(e.confidence, 4),
                "citations": _cite_str(
                    [{"doc_id": s.doc_id, "start": s.start, "end": s.end} for s in e.source_spans]
                ),
            }
            for e in self._edges
            if e.predicate not in _PLUMBING
        ]
        return self._frame(rows)

    def why(self, entity: str) -> Any:
        res = self.engine.why(entity).to_dict()
        rows = [
            {
                "subject": c["subject"],
                "predicate": c["predicate"],
                "object": c["object"],
                "polarity": c["polarity"],
                "t_valid": c.get("t_valid"),
                "t_invalid": c.get("t_invalid"),
                "citations": _cite_str(c["citations"]),
            }
            for c in res["claims"]
        ]
        return self._frame(rows)

    def neighbors(self, entity: str, *, k: int = 20) -> Any:
        res = self.engine.neighbors(entity, k=k).to_dict()
        rows = [
            {
                "direction": n["direction"],
                "predicate": n["predicate"],
                "other": n["other_name"],
                "tag": n["tag"],
                "confidence": n["confidence"],
                "citations": _cite_str(n["citations"]),
            }
            for n in res["neighbors"]
        ]
        return self._frame(rows)

    def contradictions(self) -> Any:
        rows = [
            {
                "claim_a": f"{h['claim_a']['subject']} {h['claim_a']['predicate']} "
                f"{h['claim_a']['object']}",
                "claim_b": f"{h['claim_b']['subject']} {h['claim_b']['predicate']} "
                f"{h['claim_b']['object']}",
                "recommend": h["hint"]["recommend"],
                "basis": h["hint"]["basis"],
                "reason": h["hint"]["reason"],
            }
            for h in self.engine.resolution_hints()
        ]
        return self._frame(rows)

    def roles(self, entity: str, *, k: int = 10) -> Any:
        res = self.engine.similar_roles(entity, k=k)
        rows = [
            {
                "name": m["name"],
                "similarity": m["similarity"],
                "degree": m["total_degree"],
                "top_relations": ", ".join(m["top_relations"]),
            }
            for m in res.get("matches", [])
        ]
        return self._frame(rows)
