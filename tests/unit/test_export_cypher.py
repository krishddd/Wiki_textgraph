"""openCypher export (L9) — deterministic, provenance-carrying, valid-identifier output."""

from pathlib import Path

from textgraph.l9_artifacts.cypher import _ident, export_cypher_bytes
from textgraph.pipeline import build
from textgraph.store.base import ConfidenceTag, Edge, Node, SourceSpan

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


def test_sanitizes_relationship_types_and_labels() -> None:
    assert _ident("ACTS_AS_A_FUZZER", upper=True) == "ACTS_AS_A_FUZZER"
    assert _ident("acts as a fuzzer", upper=True) == "ACTS_AS_A_FUZZER"  # spaces -> _
    assert _ident("?weird!", upper=True) == "_WEIRD_"  # non-ident chars -> _
    assert _ident("123bad")[0] in "_abcdefghijklmnopqrstuvwxyz_"  # never starts with a digit


def test_export_is_deterministic() -> None:
    r = build(DOCS)
    a = export_cypher_bytes(r.nodes, r.edges)
    b = export_cypher_bytes(list(reversed(r.nodes)), list(reversed(r.edges)))
    assert a == b  # sorted internally -> input order can't change the bytes


def test_nodes_merge_and_edges_carry_provenance() -> None:
    nodes = [
        Node("entity:a", ("Entity",), {"name": "Acme Corp", "etype": "Organization", "x": 1.0}),
        Node("entity:b", ("Entity",), {"name": "Beta Ltd"}),
    ]
    edge = Edge(
        edge_id="edge:1",
        subject="entity:a",
        predicate="CONTROLS",
        object="entity:b",
        tag=ConfidenceTag.EXTRACTED,
        confidence=0.9,
        source_spans=(SourceSpan(doc_id="doc:x", start=10, end=25, hash="abc123"),),
    )
    text = export_cypher_bytes(nodes, edges=[edge]).decode("utf-8")
    assert 'MERGE (n:Entity {id:"entity:a"})' in text
    assert 'n.name="Acme Corp"' in text
    assert "n.x=" not in text  # layout-only property is skipped
    assert "MERGE (a)-[r:CONTROLS]->(b)" in text
    # provenance survives the export
    assert 'r.tag="EXTRACTED"' in text and 'r.doc="doc:x"' in text
    assert "r.start=10" in text and "r.end=25" in text and 'r.hash="abc123"' in text


def test_escapes_quotes_in_property_values() -> None:
    nodes = [Node("entity:q", ("Entity",), {"name": 'A "quoted" name'})]
    text = export_cypher_bytes(nodes, edges=[]).decode("utf-8")
    assert '\\"quoted\\"' in text  # embedded quotes are escaped, not left raw
