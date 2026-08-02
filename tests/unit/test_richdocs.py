"""Rich-format ingestion: HTML/DOCX/ODT/RTF/EPUB (+ PDF graceful skip).

DOCX/ODT/EPUB are synthesized as minimal zip archives so no binaries are committed.
For these derived-text formats the extracted text is the canonical doc, and every
span still re-verifies against it (provenance holds).
"""

from __future__ import annotations

import io
import zipfile

import pytest
from textgraph.core.content_address import blake3_hex
from textgraph.core.layout import BlockKind
from textgraph.l0_ingest import ingest_bytes
from textgraph.l0_ingest.base import UnsupportedFormat
from textgraph.l0_ingest.richdocs import ingest_pdf


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _spans_rehash(ir) -> bool:
    for b in (bb for t in ir.blocks for bb in t.walk()):
        exp = blake3_hex(ir.text[b.span.start : b.span.end].encode("utf-8", "surrogateescape"))
        b0, b1 = ir.canonical.raw_span(b.span.start, b.span.end)
        if blake3_hex(ir.raw[b0:b1]) != exp:
            return False
    return True


def test_html_extracts_headings_and_text() -> None:
    html = b"<html><body><h1>Fraud</h1><p>Acme wired funds.</p></body></html>"
    ir = ingest_bytes(html, source_name="r.html", extension=".html")
    kinds = [b.kind for b in ir.blocks]
    assert BlockKind.HEADING in kinds and BlockKind.PARAGRAPH in kinds
    assert "Acme wired funds." in ir.text
    assert _spans_rehash(ir)


def test_docx_paragraph_styles_become_headings() -> None:
    doc = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Case Summary</w:t></w:r></w:p>'
        "<w:p><w:r><w:t>Suspect must be interviewed.</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    ir = ingest_bytes(_zip({"word/document.xml": doc}), source_name="c.docx", extension=".docx")
    assert ir.format == "docx"
    heads = [b for b in ir.blocks if b.kind is BlockKind.HEADING]
    assert heads and heads[0].text == "Case Summary"
    assert _spans_rehash(ir)


def test_odt_outline_levels() -> None:
    content = (
        '<?xml version="1.0"?>'
        "<office:document-content "
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        "<office:body><office:text>"
        '<text:h text:outline-level="1">Report</text:h>'
        "<text:p>Body paragraph.</text:p>"
        "</office:text></office:body></office:document-content>"
    )
    ir = ingest_bytes(_zip({"content.xml": content}), source_name="r.odt", extension=".odt")
    assert ir.format == "odt"
    assert any(b.kind is BlockKind.HEADING and b.text == "Report" for b in ir.blocks)
    assert _spans_rehash(ir)


def test_rtf_strips_control_words() -> None:
    rtf = rb"{\rtf1\ansi Suspicious transfer.\par Second line.\par}"
    ir = ingest_bytes(rtf, source_name="n.rtf", extension=".rtf")
    assert "Suspicious transfer." in ir.text
    assert "\\rtf1" not in ir.text
    assert _spans_rehash(ir)


def test_epub_concatenates_xhtml() -> None:
    epub = _zip(
        {
            "mimetype": "application/epub+zip",
            "OEBPS/ch1.xhtml": "<html><body><h1>Ch1</h1><p>Alpha.</p></body></html>",
            "OEBPS/ch2.xhtml": "<html><body><p>Beta.</p></body></html>",
        }
    )
    ir = ingest_bytes(epub, source_name="b.epub", extension=".epub")
    assert "Alpha." in ir.text and "Beta." in ir.text
    assert _spans_rehash(ir)


def test_corrupt_docx_raises_unsupported() -> None:
    with pytest.raises(UnsupportedFormat):
        ingest_bytes(b"not a zip", source_name="x.docx", extension=".docx")


def test_pdf_without_extra_raises_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate pypdf not installed: import inside ingest_pdf should fail -> UnsupportedFormat.
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object):
        if name == "pypdf":
            raise ImportError("no pypdf")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(UnsupportedFormat):
        ingest_pdf(b"%PDF-1.4", "x.pdf")
