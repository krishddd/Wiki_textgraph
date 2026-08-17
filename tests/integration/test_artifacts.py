"""L9 artifact integrity: schema conformance, self-contained HTML, determinism."""

import json
from pathlib import Path

import jsonschema
import pytest
from textgraph.l9_artifacts import write_artifacts
from textgraph.pipeline import build

ROOT = Path(__file__).parent.parent.parent
SCHEMA_DIR = ROOT / "schema"
CORPUS = ROOT / "tests" / "fixtures" / "corpora" / "docs"


def _write(tmp_path: Path):
    result = build(CORPUS)
    return write_artifacts(
        tmp_path,
        config_hash=result.config_hash,
        results=result.results,
        nodes=result.nodes,
        edges=result.edges,
        timings_ms=result.timings_ms,
    )


def test_graph_json_conforms_to_schema(tmp_path: Path) -> None:
    paths = _write(tmp_path)
    graph = json.loads(paths.graph_json.read_text(encoding="utf-8"))
    schema = json.loads((SCHEMA_DIR / "graph.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(graph, schema)


def test_manifest_conforms_to_schema(tmp_path: Path) -> None:
    paths = _write(tmp_path)
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    schema = json.loads((SCHEMA_DIR / "manifest.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(manifest, schema)


def test_graph_html_is_self_contained(tmp_path: Path) -> None:
    paths = _write(tmp_path)
    html = paths.graph_html.read_text(encoding="utf-8")
    # No external scripts/styles (G2: local-first viewer, no CDN).
    assert "<script src=" not in html
    assert "<link " not in html
    assert "cdn." not in html


def test_graph_html_is_the_interactive_offline_viewer(tmp_path: Path) -> None:
    # graph.html shares the console's canvas renderer and embeds everything needed to be
    # fully interactive with no server: the graph payload, per-node cited claims, and
    # the client-side path/search adapter.
    paths = _write(tmp_path)
    html = paths.graph_html.read_text(encoding="utf-8")
    assert "window.__TG_DATA__" in html  # embedded data, not an API fetch
    assert '"claims"' in html  # per-node claims for offline click-to-inspect
    assert "function clientPath" in html  # offline maximum-likelihood path
    assert "function draw()" in html and "initTime" in html  # the shared renderer


def test_graph_html_ships_the_relation_type_filter(tmp_path: Path) -> None:
    # The relation-type filter is view-only, so it must ride along in the offline viewer
    # too. Every consumer has to go through edgeShown() — if drawing filtered edges but
    # degree/neighbours/ego did not, the "unconnected" tally would contradict the canvas.
    paths = _write(tmp_path)
    html = paths.graph_html.read_text(encoding="utf-8")
    assert "function edgeShown(e)" in html
    assert "function buildPredBar()" in html
    assert "function semanticOnly()" in html
    assert "const BACKBONE = 'CO_OCCURS'" in html
    # Drawing, degree, neighbours and ego adjacency all route through the one predicate.
    assert html.count("if(!edgeShown(e)) continue;") >= 4


def test_graph_html_degrades_ask_dock_features_offline(tmp_path: Path) -> None:
    # The Ask dock's server-only features (multi-turn chat, citation source panel) must not
    # break the offline viewer: the citation click-through gates on TG.source, and the
    # offline adapter defines no such method, so chips stay inert text and the dock hides.
    paths = _write(tmp_path)
    html = paths.graph_html.read_text(encoding="utf-8")
    assert "typeof TG.source==='function'" in html  # click-through is feature-gated
    assert (
        "TG.source" not in html.split("const TG = {")[1].split("};")[0]
    )  # offline adapter lacks it
    assert 'id="srcpanel"' in html  # the panel scaffold ships (inert offline)


def test_every_non_generated_edge_has_a_citation(tmp_path: Path) -> None:
    paths = _write(tmp_path)
    graph = json.loads(paths.graph_json.read_text(encoding="utf-8"))
    for edge in graph["edges"]:
        if edge["tag"] != "GENERATED":
            assert edge["source_spans"], edge


@pytest.mark.parametrize("shape", ["docs", "adr", "chat"])
def test_report_and_html_written_for_all_shapes(tmp_path: Path, shape: str) -> None:
    corpus = ROOT / "tests" / "fixtures" / "corpora" / shape
    result = build(corpus)
    paths = write_artifacts(
        tmp_path / shape,
        config_hash=result.config_hash,
        results=result.results,
        nodes=result.nodes,
        edges=result.edges,
    )
    assert paths.graph_json.exists()
    assert paths.report.exists()
    assert paths.graph_html.exists()
