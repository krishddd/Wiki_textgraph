"""Bounding-box provenance (v5.3.0) — citations from PDFs carry an (x0,y0,x1,y1) box.

Layered additively on top of page provenance (v5.2.0): the byte range is still the identity,
re-verification never consults the box, and the field is omitted from graph.json when absent, so
text-only corpora and pre-layout graphs stay byte-identical. Coordinates are pypdf points.
"""

from __future__ import annotations

from textgraph.core.canonical_doc import CanonicalDoc
from textgraph.core.layout import IngestResult, Span
from textgraph.l0_ingest.richdocs import (
    _attach_bboxes,
    _build_bbox_map,
    _origin,
    _pdf_blocks,
    ingest_pdf,
)
from textgraph.l1_structure.emit import source_span
from textgraph.l8_retrieval.model import Citation
from textgraph.store.base import (
    ConfidenceTag,
    Edge,
    Node,
    SourceSpan,
    span_from_dict,
    span_to_dict,
)


def test_attach_bboxes_aligns_blocks_by_sequential_consumption() -> None:
    frags = [
        ("Alpha ", 0.0, 10.0, 20.0, 20.0),
        ("beta", 20.0, 10.0, 30.0, 20.0),
        ("Gamma", 0.0, 0.0, 15.0, 8.0),
    ]
    boxes = _attach_bboxes(["Alpha beta", "Gamma"], frags)
    assert boxes[0] == (0.0, 0.0 + 10.0, 30.0, 20.0)  # union of the first two fragments
    assert boxes[1] == (0.0, 0.0, 15.0, 8.0)  # the third fragment


def test_attach_bboxes_returns_none_without_fragments() -> None:
    # A page with no text layer (scanned) yields page-only provenance, never a wrong box.
    assert _attach_bboxes(["Alpha", "Beta"], []) == [None, None]


def test_build_bbox_map_groups_by_page() -> None:
    _text, blocks, _pm = _pdf_blocks(["Alpha beta", "Gamma"])
    page_fragments = [
        [("Alpha ", 1.0, 10.0, 5.0, 20.0), ("beta", 5.0, 10.0, 9.0, 20.0)],  # page 1
        [("Gamma", 2.0, 0.0, 7.0, 8.0)],  # page 2
    ]
    bmap = _build_bbox_map(blocks, page_fragments)
    # one entry per block, keyed by its canonical-char start, sorted
    assert [start for start, _box in bmap] == sorted(b.span.start for b in blocks)
    assert bmap[0][1] == (1.0, 10.0, 9.0, 20.0)  # page-1 block union
    assert bmap[1][1] == (2.0, 0.0, 7.0, 8.0)  # page-2 block


def test_origin_composes_text_and_ctm() -> None:
    # Identity ctm -> origin is just (tm[4], tm[5]).
    assert _origin([1, 0, 0, 1, 72, 700], [1, 0, 0, 1, 0, 0]) == (72, 700)
    # A translating ctm shifts the origin.
    assert _origin([1, 0, 0, 1, 10, 20], [1, 0, 0, 1, 5, 6]) == (15, 26)


def _ir_with_bbox() -> IngestResult:
    _text, blocks, page_map = _pdf_blocks(["Alpha alpha.", "Beta beta."])
    page_fragments = [
        [("Alpha alpha.", 10.0, 700.0, 90.0, 712.0)],
        [("Beta beta.", 10.0, 500.0, 70.0, 512.0)],
    ]
    bbox_map = _build_bbox_map(blocks, page_fragments)
    text = "\n\n".join(b.text for b in blocks)
    raw = text.encode("utf-8")
    return IngestResult(
        canonical=CanonicalDoc.from_bytes(raw, source_name="d.pdf"),
        raw=raw,
        source_path="d.pdf",
        format="pdf",
        blocks=blocks,
        chunks=[],
        page_map=page_map,
        bbox_map=bbox_map,
    )


def test_bbox_for_and_source_span_stamp_the_box() -> None:
    ir = _ir_with_bbox()
    first, second = ir.blocks[0], ir.blocks[1]
    assert ir.bbox_for(first.span.start) == (10.0, 700.0, 90.0, 712.0)
    sp = source_span(ir, Span(second.span.start, second.span.end))
    assert sp.page == 2 and sp.bbox == (10.0, 500.0, 70.0, 512.0)


def test_unpaged_doc_has_no_bbox() -> None:
    ir = IngestResult(
        canonical=CanonicalDoc.from_bytes(b"hi", source_name="n.txt"),
        raw=b"hi",
        source_path="n.txt",
        format="txt",
        blocks=[],
        chunks=[],
    )
    assert ir.bbox_map == () and ir.bbox_for(0) is None


def test_citation_and_span_serialization_roundtrip_bbox() -> None:
    box = (1.5, 2.5, 3.5, 4.5)
    c = Citation("blake3:d", 5, 9, "f" * 64, page=2, bbox=box)
    assert c.to_dict()["bbox"] == [1.5, 2.5, 3.5, 4.5]
    # Omitted when absent (byte-stable).
    assert "bbox" not in Citation("blake3:d", 5, 9, "f" * 64).to_dict()

    s = SourceSpan("blake3:d", 5, 9, "a" * 64, page=2, bbox=box)
    assert span_to_dict(s)["bbox"] == [1.5, 2.5, 3.5, 4.5]
    assert span_from_dict(span_to_dict(s)).bbox == box
    plain = SourceSpan("blake3:d", 5, 9, "a" * 64)
    assert "bbox" not in span_to_dict(plain)
    assert span_from_dict(span_to_dict(plain)).bbox is None


def test_cypher_and_rdf_carry_bbox() -> None:
    from textgraph.l9_artifacts.cypher import export_cypher_bytes
    from textgraph.l9_artifacts.rdf import export_rdf_bytes

    nodes = [Node("a", ("Entity",), {"name": "A"}), Node("b", ("Entity",), {"name": "B"})]
    edge = Edge(
        edge_id="edge:1",
        subject="a",
        predicate="CONTROLS",
        object="b",
        tag=ConfidenceTag.EXTRACTED,
        confidence=0.9,
        source_spans=(SourceSpan("blake3:d", 5, 9, "a" * 64, page=3, bbox=(1.0, 2.0, 3.0, 4.0)),),
    )
    cy = export_cypher_bytes(nodes, [edge]).decode("utf-8")
    assert "r.bbox=" in cy and "1.0,2.0,3.0,4.0" in cy
    ttl = export_rdf_bytes(nodes, [edge]).decode("utf-8")
    assert "tgo:sourceBBox" in ttl and "1.0 2.0 3.0 4.0" in ttl


def _positioned_pdf(pages: list[str]) -> bytes:
    """A minimal multi-page PDF with one positioned text run per page (real text layer)."""
    body = b""
    offsets: list[int] = []
    head = b"%PDF-1.4\n"

    def add(obj: bytes) -> None:
        nonlocal body
        offsets.append(len(head) + len(body))
        body += obj

    n = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    add(b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n")
    add(f"2 0 obj<</Type/Pages/Count {n}/Kids[{kids}]>>endobj\n".encode())
    add(b"3 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n")
    for i, t in enumerate(pages):
        page_obj, content_obj = 4 + 2 * i, 5 + 2 * i
        add(
            f"{page_obj} 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
            f"/Resources<</Font<</F1 3 0 R>>>>/Contents {content_obj} 0 R>>endobj\n".encode()
        )
        stream = f"BT /F1 12 Tf 72 700 Td ({t}) Tj ET".encode()
        obj = f"{content_obj} 0 obj<</Length {len(stream)}>>stream\n".encode()
        add(obj + stream + b"\nendstream endobj\n")
    xref_pos = len(head) + len(body)
    total = len(offsets) + 1
    xref = f"xref\n0 {total}\n0000000000 65535 f \n".encode()
    for off in offsets:
        xref += f"{off:010d} 00000 n \n".encode()
    trailer = f"trailer<</Size {total}/Root 1 0 R>>\nstartxref\n{xref_pos}\n%%EOF".encode()
    return head + body + xref + trailer


def test_ingest_pdf_end_to_end_stamps_page_bbox_and_page_size() -> None:
    ir = ingest_pdf(
        _positioned_pdf(["Acme Corp controls Beta Ltd.", "Gamma owns Delta Trust."]),
        "case.pdf",
    )
    assert [b.props.get("page") for b in ir.blocks] == [1, 2]
    assert ir.page_map[0] == (0, 1) and ir.page_map[1][1] == 2
    # Every block got a real bounding box near the text origin (72, 700).
    assert len(ir.bbox_map) == 2
    for _start, box in ir.bbox_map:
        x0, y0, x1, y1 = box
        assert x0 == 72.0 and y0 == 700.0 and x1 > x0 and y1 > y0
    # Page sizes come from the MediaBox (Letter, 612 x 792) — one per page.
    assert ir.page_sizes == ((612.0, 792.0), (612.0, 792.0))
    assert ir.page_size_for(2) == (612.0, 792.0) and ir.page_size_for(3) is None
    # A citation minted from the second block carries page, bbox, and the page size.
    sp = source_span(ir, Span(ir.blocks[1].span.start, ir.blocks[1].span.end))
    assert sp.page == 2 and sp.bbox is not None and sp.page_size == (612.0, 792.0)


def test_page_size_roundtrips_through_serialization() -> None:
    box = (1.0, 2.0, 3.0, 4.0)
    c = Citation("blake3:d", 5, 9, "f" * 64, page=2, bbox=box, page_size=(612.0, 792.0))
    assert c.to_dict()["page_size"] == [612.0, 792.0]
    assert "page_size" not in Citation("blake3:d", 5, 9, "f" * 64).to_dict()

    s = SourceSpan("blake3:d", 5, 9, "a" * 64, page=2, bbox=box, page_size=(612.0, 792.0))
    assert span_to_dict(s)["page_size"] == [612.0, 792.0]
    assert span_from_dict(span_to_dict(s)).page_size == (612.0, 792.0)
    assert "page_size" not in span_to_dict(SourceSpan("blake3:d", 5, 9, "a" * 64))
