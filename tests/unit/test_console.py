"""Console API routing — the pure request→response function, no socket."""

import json
from pathlib import Path

from textgraph.console.api import route
from textgraph.l8_retrieval import QueryEngine
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"
TEMPORAL = Path(__file__).parent.parent / "fixtures" / "corpora" / "temporal"


def _engine(corpus: Path = DOCS) -> QueryEngine:
    r = build(corpus)
    return QueryEngine(r.nodes, r.edges)


def test_index_serves_self_contained_html() -> None:
    status, ctype, body = route(_engine(), "/", {})
    assert status == 200
    assert "text/html" in ctype
    html = body.decode("utf-8")
    assert "TextGraph Console" in html
    # G2: no external requests — no CDN scripts/styles.
    assert "<script src=" not in html
    assert "cdn." not in html


def test_tools_endpoint_lists_eight_tools() -> None:
    status, ctype, body = route(_engine(), "/api/tools", {})
    assert status == 200 and "application/json" in ctype
    tools = json.loads(body)["tools"]
    assert len(tools) == 8


def test_search_call_returns_cited_hits() -> None:
    status, _, body = route(_engine(), "/api/call", {"tool": "search", "query": "funds", "k": "3"})
    assert status == 200
    payload = json.loads(body)
    assert payload["tool"] == "search"
    assert payload["hits"]


def test_path_call_coerces_int_and_returns_paths() -> None:
    status, _, body = route(
        _engine(),
        "/api/call",
        {"tool": "path", "source": "Acme Corp", "target": "Gamma Holdings", "k": "2"},
    )
    assert status == 200
    assert json.loads(body)["tool"] == "path"


def test_unknown_tool_is_400() -> None:
    status, _, body = route(_engine(), "/api/call", {"tool": "nope"})
    assert status == 400
    assert "unknown tool" in json.loads(body)["error"]


def test_unknown_path_is_404() -> None:
    status, _, _ = route(_engine(), "/favicon.ico", {})
    assert status == 404


def test_graph_endpoint_returns_laid_out_nodes_and_communities() -> None:
    status, ctype, body = route(_engine(), "/api/graph", {})
    assert status == 200 and "application/json" in ctype
    g = json.loads(body)
    assert g["nodes"] and g["edges"] and g["communities"]
    for n in g["nodes"]:
        assert {"id", "name", "x", "y", "community", "pagerank"} <= set(n)
    # Roster carries labels + sizes for the sidebar.
    assert all("label" in c and "size" in c for c in g["communities"])


def test_graph_endpoint_is_bounded_and_reports_truncation() -> None:
    _, _, body = route(_engine(), "/api/graph", {"max_nodes": "3"})
    g = json.loads(body)
    assert g["shown"] <= 3
    assert g["truncated"] is (g["total"] > g["shown"])


def test_graph_edges_carry_temporal_windows_for_the_slider() -> None:
    # The temporal fixture has a 2026-05-01 transfer superseded by a 2026-06-01
    # correction; the graph payload must expose both dates + per-edge windows so the
    # console's time scrubber can fade the superseded edge.
    _, _, body = route(_engine(TEMPORAL), "/api/graph", {})
    g = json.loads(body)
    assert g["dates"] == ["2026-05-01", "2026-06-01"]
    transfers = [e for e in g["edges"] if e["predicate"] == "TRANSFERRED"]
    windows = {(e["t_valid"], e["t_invalid"]) for e in transfers}
    assert ("2026-05-01", "2026-06-01") in windows  # the superseded assertion
    assert ("2026-06-01", None) in windows  # the current correction
