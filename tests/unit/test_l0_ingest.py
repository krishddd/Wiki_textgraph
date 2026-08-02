from textgraph.core.layout import BlockKind
from textgraph.l0_ingest import ingest_bytes


def _kinds(ir):
    return [b.kind for b in (bb for top in ir.blocks for bb in top.walk())]


def test_markdown_headings_have_exact_spans() -> None:
    raw = b"# Title\n\nA paragraph with a [[WikiTarget]].\n\n## Sub\n\nMore text.\n"
    ir = ingest_bytes(raw, source_name="d.md", extension=".md")
    headings = [
        b for b in (bb for t in ir.blocks for bb in t.walk()) if b.kind is BlockKind.HEADING
    ]
    assert [h.text for h in headings] == ["Title", "Sub"]
    # The heading span re-slices to the exact source line.
    h = headings[0]
    assert ir.text[h.span.start : h.span.end].strip().startswith("# Title")


def test_plaintext_paragraphs() -> None:
    ir = ingest_bytes(b"Para one.\n\nPara two.\n", source_name="d.txt", extension=".txt")
    assert BlockKind.PARAGRAPH in _kinds(ir)
    assert ir.format == "plaintext"


def test_log_templating_masks_variables() -> None:
    raw = (
        b"2026-08-01 10:00:00 INFO login from 10.0.0.1\n"
        b"2026-08-01 10:05:00 INFO login from 10.0.0.9\n"
    )
    ir = ingest_bytes(raw, source_name="a.log", extension=".log")
    templates = {b.props["template"] for b in ir.blocks}
    # Both lines collapse to one masked template.
    assert len(templates) == 1
    assert "<IP>" in next(iter(templates))


def test_structured_json_fields() -> None:
    raw = b'{"owner": {"name": "Acme"}, "amount": 1200000}'
    ir = ingest_bytes(raw, source_name="a.json", extension=".json")
    paths = {b.props.get("path") for b in ir.blocks}
    assert "owner.name" in paths
    assert "amount" in paths


def test_transcript_speakers() -> None:
    raw = b"[10:00] Alice: hello\nBob: hi there\n"
    ir = ingest_bytes(raw, source_name="c.chat", extension=".chat")
    speakers = {b.props["speaker"] for b in ir.blocks}
    assert speakers == {"Alice", "Bob"}


def test_unknown_extension_falls_back_to_plaintext() -> None:
    ir = ingest_bytes(b"just text", source_name="x.unknown", extension=".unknown")
    assert ir.format == "plaintext"


def test_empty_document_degrades() -> None:
    ir = ingest_bytes(b"", source_name="empty.md", extension=".md")
    assert ir.blocks == []
    assert ir.chunks == []


def test_ingest_is_deterministic() -> None:
    raw = b"# H\n\nText [[A]] and [1].\n"
    a = ingest_bytes(raw, source_name="d.md", extension=".md")
    b = ingest_bytes(raw, source_name="d.md", extension=".md")
    assert a.doc_id == b.doc_id
    assert [x.chunk_id for x in a.chunks] == [x.chunk_id for x in b.chunks]
