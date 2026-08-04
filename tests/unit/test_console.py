"""Console API routing — the pure request→response function, no socket."""

import json
from pathlib import Path

from textgraph.console.api import route
from textgraph.l8_retrieval import QueryEngine
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


def _engine() -> QueryEngine:
    r = build(DOCS)
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
