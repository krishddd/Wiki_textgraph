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


def test_cooccurrence_backbone_connects_a_relationless_graph() -> None:
    # A build that names entities but states few explicit relations should still render a
    # connected map: the console derives CO_OCCURS edges from shared passages so the layout
    # spreads instead of collapsing to a ring. Simulate by stripping the relation edges.
    from textgraph.l8_retrieval.engine import _NON_RELATION

    r = build(DOCS)
    plumbing = _NON_RELATION | {"HAS_CHUNK"}
    stripped = [e for e in r.edges if e.predicate in plumbing]  # keep MENTIONS, drop relations
    eng = QueryEngine(r.nodes, stripped)
    gv = eng.graph_view(max_nodes=600)
    cooc = [e for e in gv["edges"] if e["predicate"] == "CO_OCCURS"]
    assert cooc, "expected co-occurrence edges when the graph has no explicit relations"
    assert all(e["tag"] == "STRUCTURAL" for e in cooc)


def test_graph_view_reports_per_entity_contradiction_counts() -> None:
    # The contradiction heatmap needs a per-node contested-claim count. A CONTRADICTS edge
    # links two Claim nodes; each claim's `subject` names the entity it is about, so the
    # count is attributed back to the entity. The temporal fixture states a fact and a dated
    # correction of it, producing one CONTRADICTS pair about a single entity.
    r = build(TEMPORAL)
    gv = QueryEngine(r.nodes, r.edges).graph_view(max_nodes=600)
    assert all("contradictions" in n for n in gv["nodes"])  # field always present (0 default)
    flagged = {n["name"]: n["contradictions"] for n in gv["nodes"] if n["contradictions"]}
    assert flagged, "temporal fixture should surface at least one contested entity"
    assert all(v > 0 for v in flagged.values())


def test_graph_view_contradiction_counts_zero_without_conflicts() -> None:
    # The plain docs build has no dated corrections, so nothing is contested.
    r = build(DOCS)
    gv = QueryEngine(r.nodes, r.edges).graph_view(max_nodes=600)
    assert all(n["contradictions"] == 0 for n in gv["nodes"])


def test_cooccurrence_backbone_suppressed_when_relations_exist() -> None:
    # The normal build has real relations, so the co-occurrence fallback must stay off.
    r = build(DOCS)
    gv = QueryEngine(r.nodes, r.edges).graph_view(max_nodes=600)
    assert not [e for e in gv["edges"] if e["predicate"] == "CO_OCCURS"]


def test_llm_relation_endpoints_shown_despite_low_pagerank() -> None:
    # A GENERATED (LLM-extracted) relation connects low-PageRank entity:LLM: nodes. Even when
    # the view is capped below the number of higher-ranked entities, those endpoints and the
    # relation must appear — otherwise the meaningful X -PRED-> Y edges the user built stay
    # invisible under the rank cutoff.
    from textgraph.store.base import ConfidenceTag, Edge, Node

    nodes = [
        Node(f"entity:hi:{i}", ("Entity",), {"name": f"Hi{i}", "pagerank": 0.9 - i * 0.01})
        for i in range(10)
    ]
    a = Node("entity:LLM:alpha", ("Entity",), {"name": "Alpha", "pagerank": 0.0, "etype": "LLM"})
    b = Node("entity:LLM:beta", ("Entity",), {"name": "Beta", "pagerank": 0.0, "etype": "LLM"})
    nodes += [a, b]
    edge = Edge(
        edge_id="edge:1",
        subject=a.node_id,
        predicate="REGULATES",
        object=b.node_id,
        tag=ConfidenceTag.GENERATED,
        confidence=0.5,
    )
    gv = QueryEngine(nodes, [edge]).graph_view(max_nodes=5)  # cap below the 10 hi-rank entities
    shown = {n["id"] for n in gv["nodes"]}
    assert {a.node_id, b.node_id} <= shown
    assert any(e["predicate"] == "REGULATES" for e in gv["edges"])


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


def test_inspect_endpoint_returns_admin_detail() -> None:
    import json as _json

    # A corpus with an alias so SAME_AS clustering shows up in the admin view.
    import tempfile
    from pathlib import Path

    from textgraph.l8_retrieval import QueryEngine
    from textgraph.pipeline import build

    d = Path(tempfile.mkdtemp())
    (d / "a.md").write_text(
        "Acme Corporation controls Gamma Holdings. Acme Corp wired funds to Beta Ltd. "
        "ACME is the parent.",
        encoding="utf-8",
    )
    r = build(d)
    eng = QueryEngine(r.nodes, r.edges)
    status, ctype, body = route(eng, "/api/inspect", {"node": "Acme Corp"})
    assert status == 200 and "application/json" in ctype
    payload = _json.loads(body)
    assert payload["found"] is True
    assert payload["same_as"]["canonical"]  # alias cluster surfaced
    assert "confidence_tiers" in payload and "provenance" in payload and "claims" in payload


def test_export_graph_bytes_is_valid_graph_json() -> None:
    import json as _json
    from pathlib import Path

    from textgraph.console.api import export_graph_bytes
    from textgraph.l8_retrieval import QueryEngine
    from textgraph.pipeline import build

    DOCS2 = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"
    r = build(DOCS2)
    body = export_graph_bytes(QueryEngine(r.nodes, r.edges))
    assert body.endswith(b"\n")  # canonical JSON, trailing newline
    doc = _json.loads(body)
    assert {"schema_version", "tool_version", "nodes", "edges", "stats"} <= doc.keys()
    assert doc["stats"]["node_count"] == len(doc["nodes"]) == len(r.nodes)
    assert len(doc["edges"]) == len(r.edges)
    # Deterministic: same graph -> byte-identical export.
    assert export_graph_bytes(QueryEngine(r.nodes, r.edges)) == body


def test_console_serves_a_prebuilt_graph_json(tmp_path: Path) -> None:
    # `textgraph console textgraph-out/graph.json` (or the output dir) serves the ALREADY
    # built graph -- so an LLM-enriched build shows all its relations, no silent rebuild.
    from textgraph.console.server import build_engine
    from textgraph.l9_artifacts.graph_json import load_graph_json
    from textgraph.pipeline import build_graph_bytes

    out = tmp_path / "graph.json"
    out.write_bytes(build_graph_bytes(DOCS))
    r = build(DOCS)

    nodes, edges = load_graph_json(out)
    assert len(nodes) == len(r.nodes) and len(edges) == len(r.edges)
    # tags + spans survive the round-trip (provenance intact).
    assert {str(e.tag) for e in edges} == {str(e.tag) for e in r.edges}
    assert any(e.source_spans for e in edges)

    # build_engine accepts the graph.json file AND its containing directory.
    assert build_engine(out).search("Acme", k=3).to_dict()["hits"]
    assert build_engine(tmp_path).search("Acme", k=3).to_dict()["hits"]


def test_list_and_remove_documents(tmp_path: Path) -> None:
    from textgraph.console.ingest import list_documents, remove_document

    (tmp_path / "a.md").write_text("Acme Corp controls Beta Ltd.", encoding="utf-8")
    (tmp_path / "b.md").write_text("Gamma Holdings owns Delta Trust.", encoding="utf-8")
    names = [d["name"] for d in list_documents(tmp_path)]
    assert names == ["a.md", "b.md"]

    res = remove_document(tmp_path, "a.md")
    assert res.ok and not (tmp_path / "a.md").exists()
    assert [d["name"] for d in list_documents(tmp_path)] == ["b.md"]
    assert res.nodes  # graph rebuilt from what remains


def test_remove_document_is_traversal_safe(tmp_path: Path) -> None:
    from textgraph.console.ingest import remove_document

    (tmp_path / "keep.md").write_text("x", encoding="utf-8")
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("do not delete", encoding="utf-8")
    assert not remove_document(tmp_path, "../secret.txt").ok  # escapes the corpus -> refused
    assert not remove_document(tmp_path, "missing.md").ok  # absent -> refused
    assert outside.exists()  # untouched


def test_list_documents_empty_for_non_directory(tmp_path: Path) -> None:
    from textgraph.console.ingest import list_documents

    gj = tmp_path / "graph.json"
    gj.write_text("{}", encoding="utf-8")
    assert list_documents(gj) == []  # a snapshot has no editable corpus behind it
