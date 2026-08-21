"""Page provenance (v5.2.0) — paged sources (PDFs) stamp a 1-based page on every citation.

Additive layout metadata on top of the byte-span citation (G3): the byte range stays the
identity and re-verification never consults the page, so text corpora and pre-page graphs are
byte-identical (the field is omitted from graph.json when 0).
"""

from __future__ import annotations

from textgraph.core.canonical_doc import CanonicalDoc
from textgraph.core.layout import BlockKind, IngestResult
from textgraph.l0_ingest.richdocs import _pdf_blocks
from textgraph.l1_structure.emit import source_span
from textgraph.l8_retrieval.model import Citation
from textgraph.store.base import ConfidenceTag, Edge, SourceSpan


def _ingest_from(page_texts: list[str]) -> IngestResult:
    text, blocks, page_map = _pdf_blocks(page_texts)
    raw = text.encode("utf-8")
    canonical = CanonicalDoc.from_bytes(raw, source_name="doc.pdf")
    return IngestResult(
        canonical=canonical,
        raw=raw,
        source_path="doc.pdf",
        format="pdf",
        blocks=blocks,
        chunks=[],
        page_map=page_map,
    )


def test_pdf_blocks_stamp_page_and_build_a_page_map() -> None:
    text, blocks, page_map = _pdf_blocks(["First page para.", "Second page para."])
    assert [b.props["page"] for b in blocks] == [1, 2]
    assert [b.kind for b in blocks] == [BlockKind.PARAGRAPH, BlockKind.PARAGRAPH]
    # page 1 begins at offset 0; page 2 begins after "First page para.\n\n"
    assert page_map[0] == (0, 1)
    assert page_map[1][1] == 2
    assert page_map[1][0] == len("First page para.") + 2
    assert "First page para." in text and "Second page para." in text


def test_blank_pages_are_skipped_but_do_not_renumber() -> None:
    # Page 2 is blank; page 3 must still report page 3, not 2.
    _text, blocks, page_map = _pdf_blocks(["Alpha.", "   ", "Gamma."])
    assert [b.props["page"] for b in blocks] == [1, 3]
    assert [p for _off, p in page_map] == [1, 3]


def test_page_for_resolves_offsets_to_pages() -> None:
    ir = _ingest_from(["Alpha alpha.", "Beta beta beta."])
    boundary = ir.page_map[1][0]
    assert ir.page_for(0) == 1
    assert ir.page_for(boundary - 1) == 1
    assert ir.page_for(boundary) == 2
    assert ir.page_for(boundary + 3) == 2


def test_unpaged_doc_reports_page_zero() -> None:
    ir = IngestResult(
        canonical=CanonicalDoc.from_bytes(b"hello", source_name="n.txt"),
        raw=b"hello",
        source_path="n.txt",
        format="txt",
        blocks=[],
        chunks=[],
    )
    assert ir.page_map == ()
    assert ir.page_for(0) == 0


def test_source_span_stamps_the_page() -> None:
    from textgraph.core.layout import Span

    ir = _ingest_from(["Alpha alpha.", "Beta beta beta."])
    # A span on the second page's block resolves to page 2.
    second = next(b for b in ir.blocks if b.props["page"] == 2)
    sp = source_span(ir, Span(second.span.start, second.span.end))
    assert sp.page == 2
    # A span on the first block resolves to page 1.
    first = ir.blocks[0]
    assert source_span(ir, Span(first.span.start, first.span.end)).page == 1


def test_citation_ref_and_dict_carry_page() -> None:
    paged = Citation("blake3:abc", 10, 25, "f" * 64, page=4)
    assert paged.ref() == "[p.4 blake3:abc:10-25]"
    assert paged.to_dict()["page"] == 4
    # Unpaged: no page in ref or dict (back-compat, byte-stable).
    plain = Citation("blake3:abc", 10, 25, "f" * 64)
    assert plain.ref() == "[blake3:abc:10-25]"
    assert "page" not in plain.to_dict()


def test_graph_json_roundtrips_page_and_omits_it_when_zero() -> None:
    import json

    from textgraph.l9_artifacts.graph_json import _edge_dict, load_graph_json

    paged = Edge(
        edge_id="edge:1",
        subject="a",
        predicate="CONTROLS",
        object="b",
        tag=ConfidenceTag.STRUCTURAL,
        confidence=1.0,
        source_spans=(SourceSpan("blake3:d", 5, 9, "a" * 64, page=7),),
    )
    plain = Edge(
        edge_id="edge:2",
        subject="a",
        predicate="CONTROLS",
        object="c",
        tag=ConfidenceTag.STRUCTURAL,
        confidence=1.0,
        source_spans=(SourceSpan("blake3:d", 5, 9, "a" * 64),),
    )
    assert _edge_dict(paged)["source_spans"][0]["page"] == 7
    assert "page" not in _edge_dict(plain)["source_spans"][0]  # omitted when 0 -> byte-stable

    # Round-trip through a written graph.json shape.
    doc = {
        "nodes": [],
        "edges": [{**_edge_dict(paged), "properties": {}}],
    }
    from pathlib import Path
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as d:
        p = Path(d) / "graph.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        _nodes, edges = load_graph_json(p)
    assert edges[0].source_spans[0].page == 7


def test_cypher_and_rdf_carry_page_when_present() -> None:
    from textgraph.l9_artifacts.cypher import export_cypher_bytes
    from textgraph.l9_artifacts.rdf import export_rdf_bytes
    from textgraph.store.base import Node

    nodes = [
        Node("a", ("Entity",), {"name": "Acme"}),
        Node("b", ("Entity",), {"name": "Beta"}),
    ]
    edge = Edge(
        edge_id="edge:1",
        subject="a",
        predicate="CONTROLS",
        object="b",
        tag=ConfidenceTag.EXTRACTED,
        confidence=0.9,
        source_spans=(SourceSpan("blake3:d", 5, 9, "a" * 64, page=3),),
    )
    cy = export_cypher_bytes(nodes, [edge]).decode("utf-8")
    assert "r.page=3" in cy
    ttl = export_rdf_bytes(nodes, [edge]).decode("utf-8")
    assert "tgo:sourcePage" in ttl and '"3"' in ttl
