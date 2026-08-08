"""RDF / OWL / SHACL export — deterministic, valid Turtle triple-store artifacts."""

from pathlib import Path

import pytest
from textgraph.cli import main
from textgraph.l9_artifacts.ontology import export_owl_bytes, export_shacl_bytes
from textgraph.l9_artifacts.rdf import export_rdf_bytes
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


def _built() -> object:
    return build(DOCS)


# --- RDF (Turtle) ------------------------------------------------------------


def test_rdf_has_prefixes_classes_and_relations() -> None:
    r = _built()
    ttl = export_rdf_bytes(r.nodes, r.edges).decode("utf-8")
    assert ttl.startswith("@prefix")
    assert "@prefix rdf:" in ttl and "@prefix prov:" in ttl
    assert "a <https://textgraph.dev/class/" in ttl  # node typed by its label
    assert "<https://textgraph.dev/rel/" in ttl  # relation predicate triples
    assert ttl.endswith("\n")


def test_rdf_reifies_provenance_for_cited_edges() -> None:
    r = _built()
    ttl = export_rdf_bytes(r.nodes, r.edges).decode("utf-8")
    # Cited edges become rdf:Statement with the re-verifiable byte span (G3).
    assert "a rdf:Statement" in ttl
    assert "tgo:sourceHash" in ttl and "prov:wasDerivedFrom" in ttl
    assert "tgo:confidenceTag" in ttl


def test_rdf_is_deterministic() -> None:
    r = _built()
    assert export_rdf_bytes(r.nodes, r.edges) == export_rdf_bytes(r.nodes, r.edges)


# --- OWL ---------------------------------------------------------------------


def test_owl_declares_classes_and_object_properties() -> None:
    r = _built()
    owl = export_owl_bytes(r.nodes, r.edges).decode("utf-8")
    assert "owl:Class" in owl
    assert "owl:ObjectProperty" in owl
    assert "owl:DatatypeProperty" in owl  # scalar property keys
    assert export_owl_bytes(r.nodes, r.edges) == export_owl_bytes(r.nodes, r.edges)


# --- SHACL -------------------------------------------------------------------


def test_shacl_emits_node_shapes_per_class() -> None:
    r = _built()
    shacl = export_shacl_bytes(r.nodes, r.edges).decode("utf-8")
    assert "sh:NodeShape" in shacl
    assert "sh:targetClass" in shacl
    assert "sh:property" in shacl and "sh:minCount 1" in shacl
    assert export_shacl_bytes(r.nodes, r.edges) == export_shacl_bytes(r.nodes, r.edges)


# --- validity (optional, only if rdflib happens to be installed) -------------


def test_all_exports_are_valid_turtle() -> None:
    rdflib = pytest.importorskip("rdflib")
    r = _built()
    for fn in (export_rdf_bytes, export_owl_bytes, export_shacl_bytes):
        g = rdflib.Graph()
        g.parse(data=fn(r.nodes, r.edges).decode("utf-8"), format="turtle")
        assert len(g) > 0  # parsed into real triples


# --- CLI ---------------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["rdf", "owl", "shacl"])
def test_export_cli_writes_file(fmt: str, tmp_path: Path) -> None:
    out = tmp_path / f"graph.{fmt}"
    assert main(["export", str(DOCS), "--format", fmt, "-o", str(out)]) == 0
    body = out.read_text(encoding="utf-8")
    assert body.startswith("@prefix") and body.endswith("\n")


def test_export_cli_rdf_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["export", str(DOCS), "--format", "rdf"]) == 0
    out = capsys.readouterr().out
    assert "@prefix tg:" in out and "class/" in out
