from textgraph.l0_ingest import ingest_bytes
from textgraph.l1_structure import parse_corpus


def _build(raw: bytes, name: str, ext: str):
    return parse_corpus([ingest_bytes(raw, source_name=name, extension=ext)])


def _preds(edges):
    return {e.predicate for e in edges}


def _labels(nodes):
    return {label for n in nodes for label in n.labels}


def test_section_hierarchy_contains() -> None:
    raw = b"# A\n\ntext\n\n## B\n\nmore\n"
    nodes, edges = _build(raw, "d.md", ".md")
    assert "Section" in _labels(nodes)
    assert "CONTAINS" in _preds(edges)
    # A CONTAINS B (section under section) exists somewhere.
    sections = {n.node_id for n in nodes if "Section" in n.labels}
    assert any(
        e.subject in sections and e.object in sections for e in edges if e.predicate == "CONTAINS"
    )


def test_wikilink_and_url_links() -> None:
    raw = b"See [[Target]] and https://example.org/x here.\n"
    nodes, edges = _build(raw, "d.md", ".md")
    assert "LINKS_TO" in _preds(edges)
    assert any("Reference" in n.labels for n in nodes)


def test_definition_creates_term() -> None:
    raw = b"Structuring: breaking a transfer into small deposits to avoid thresholds.\n"
    nodes, edges = _build(raw, "d.md", ".md")
    assert "DEFINES" in _preds(edges)
    assert any(n.properties.get("name") == "Structuring" for n in nodes if "Term" in n.labels)


def test_rationale_and_requirement() -> None:
    raw = b"# X\n\nWHY: we chose this. The system MUST cite sources.\n"
    nodes, edges = _build(raw, "d.md", ".md")
    assert "Rationale" in _labels(nodes)
    assert "Requirement" in _labels(nodes)
    assert "APPLIES_TO" in _preds(edges)
    assert "STATES_REQUIREMENT" in _preds(edges)


def test_citation_edge() -> None:
    raw = b"As shown in [12], the pattern holds.\n"
    _nodes, edges = _build(raw, "d.md", ".md")
    assert "CITES" in _preds(edges)


def test_transcript_threads() -> None:
    raw = b"Alice: first\nBob: second\nAlice: third\n"
    nodes, edges = _build(raw, "c.chat", ".chat")
    assert "Participant" in _labels(nodes)
    assert "Message" in _labels(nodes)
    assert "REPLIES_TO" in _preds(edges)
    assert "SENT_BY" in _preds(edges)


def test_every_edge_is_structural_with_span() -> None:
    raw = b"# H\n\nWHY: reason. [[Link]] and [1].\n"
    _nodes, edges = _build(raw, "d.md", ".md")
    assert edges
    for e in edges:
        assert str(e.tag) == "STRUCTURAL"
        assert e.confidence == 1.0
        assert e.source_spans and all(s.hash for s in e.source_spans)


def test_parse_is_deterministic() -> None:
    raw = b"# H\n\nWHY: reason. [[Link]].\n"
    n1, e1 = _build(raw, "d.md", ".md")
    n2, e2 = _build(raw, "d.md", ".md")
    assert [n.node_id for n in n1] == [n.node_id for n in n2]
    assert [e.edge_id for e in e1] == [e.edge_id for e in e2]
