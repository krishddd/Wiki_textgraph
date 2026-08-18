"""SKOS export — communities as a concept scheme, aliases as altLabels."""

from pathlib import Path

from textgraph.l9_artifacts.skos import export_skos_bytes
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


def _skos(nodes, edges) -> str:
    return export_skos_bytes(nodes, edges).decode("utf-8")


def test_skos_is_a_concept_scheme_with_topics_and_terms() -> None:
    r = build(DOCS)
    ttl = _skos(r.nodes, r.edges)
    assert "@prefix skos: <http://www.w3.org/2004/02/skos/core#> ." in ttl
    assert "skos:ConceptScheme" in ttl
    assert "skos:topConceptOf" in ttl  # communities are top concepts
    assert "skos:broader" in ttl and "skos:narrower" in ttl  # entity <-> community hierarchy
    assert "skos:inScheme" in ttl


def test_skos_is_deterministic(tmp_path: Path) -> None:
    r = build(DOCS)
    a = export_skos_bytes(r.nodes, r.edges)
    b = export_skos_bytes(list(reversed(r.nodes)), list(reversed(r.edges)))
    assert a == b  # sorted emission -> order-independent (G1)


def test_same_as_aliases_become_altlabels(tmp_path: Path) -> None:
    d = tmp_path / "c"
    d.mkdir()
    (d / "f.md").write_text(
        "# Case\nAcme Corporation controls Beta Ltd.\nAcme Corp transferred $1 to Beta Ltd.\n"
        "ACME is under review.\n",
        encoding="utf-8",
    )
    r = build(d)
    ttl = _skos(r.nodes, r.edges)
    # The canonical concept collects its resolved variants as alternative labels.
    assert 'skos:prefLabel "Acme Corporation"' in ttl
    assert 'skos:altLabel "ACME"' in ttl or 'skos:altLabel "Acme Corp"' in ttl


def test_skos_export_via_cli(tmp_path: Path) -> None:
    from textgraph.cli import main

    out = tmp_path / "concepts.ttl"
    assert main(["export", str(DOCS), "--format", "skos", "-o", str(out)]) == 0
    assert out.is_file()
    assert "skos:ConceptScheme" in out.read_text(encoding="utf-8")
