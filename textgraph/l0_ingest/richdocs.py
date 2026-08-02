"""Rich-document ingestors (L0): HTML, DOCX, ODT, RTF, EPUB, PDF.

These formats do not store their text as a byte-substring of the file, so the
*extracted* plain text becomes the canonical document (see ``canonical_from_text``)
and provenance spans re-verify against that extracted text. Structure (headings vs
paragraphs) is recovered deterministically from each format's native markup:

  * HTML/XHTML/EPUB  -> stdlib ``html.parser`` (heading tags, paragraphs, lists)
  * DOCX/ODT         -> stdlib ``zipfile`` + XML (paragraph styles / outline levels)
  * RTF              -> control-word stripping into paragraphs
  * PDF              -> ``pypdf`` if installed (``textgraph[ingest]``), else skipped

All are dependency-free except PDF. Everything is deterministic (G1).
"""

from __future__ import annotations

import io
import re
import zipfile
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

from textgraph.core.layout import Block, BlockKind, IngestResult, Span
from textgraph.l0_ingest.base import (
    UnsupportedFormat,
    canonical_from_text,
    make_chunks,
    register,
)


def _result_from_blocks(text: str, blocks: list[Block], source_name: str, fmt: str) -> IngestResult:
    canonical, raw = canonical_from_text(text, source_name)
    chunks = make_chunks(canonical.doc_id, text, blocks)
    return IngestResult(
        canonical=canonical,
        raw=raw,
        source_path=source_name,
        format=fmt,
        blocks=blocks,
        chunks=chunks,
    )


def _blocks_from_lines(lines: list[tuple[str, int]]) -> tuple[str, list[Block]]:
    """Assemble canonical text + span-carrying blocks from ``(text, level)`` items.

    ``level`` 0 = paragraph; 1-6 = heading level. Offsets index the joined text.
    """
    parts: list[str] = []
    blocks: list[Block] = []
    pos = 0
    for content, level in lines:
        content = content.strip()
        if not content:
            continue
        start = pos
        end = start + len(content)
        kind = BlockKind.HEADING if level > 0 else BlockKind.PARAGRAPH
        blocks.append(Block(kind, Span(start, end), content, level=level))
        parts.append(content)
        pos = end + 2  # account for the "\n\n" separator we join with
    return "\n\n".join(parts), blocks


# --- HTML / XHTML / EPUB -----------------------------------------------------
_BLOCK_TAGS = {"p", "li", "blockquote", "pre", "td", "th", "dd", "dt", "figcaption"}
_HEADINGS = {f"h{i}": i for i in range(1, 7)}
_SKIP = {"script", "style", "head", "nav", "footer"}


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[tuple[str, int]] = []
        self._buf: list[str] = []
        self._level = 0
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _SKIP:
            self._skip += 1
        elif tag in _HEADINGS:
            self._flush()
            self._level = _HEADINGS[tag]
        elif tag in _BLOCK_TAGS or tag in ("br", "div"):
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag in _HEADINGS or tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self._buf.append(data)

    def _flush(self) -> None:
        if self._buf:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if text:
                self.lines.append((text, self._level))
            self._buf = []
        self._level = 0

    def close(self) -> None:
        super().close()
        self._flush()


def _html_to_lines(html: str) -> list[tuple[str, int]]:
    parser = _HTMLText()
    parser.feed(html)
    parser.close()
    return parser.lines


@register(".html", ".htm", ".xhtml")
def ingest_html(raw: bytes, source_name: str) -> IngestResult:
    html = raw.decode("utf-8", errors="surrogateescape")
    text, blocks = _blocks_from_lines(_html_to_lines(html))
    return _result_from_blocks(text, blocks, source_name, "html")


# --- DOCX --------------------------------------------------------------------
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@register(".docx")
def ingest_docx(raw: bytes, source_name: str) -> IngestResult:
    try:
        with zipfile.ZipFile(_bytes_io(raw)) as zf:
            xml = zf.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise UnsupportedFormat(f"not a readable .docx ({exc})") from exc
    root = ET.fromstring(xml)
    lines: list[tuple[str, int]] = []
    for para in root.iter(f"{_W}p"):
        text = "".join(t.text or "" for t in para.iter(f"{_W}t"))
        if not text.strip():
            continue
        style = para.find(f"{_W}pPr/{_W}pStyle")
        val = style.get(f"{_W}val", "") if style is not None else ""
        m = re.search(r"(\d)", val) if "eading" in val.lower() else None
        level = int(m.group(1)) if m else 0
        lines.append((text, level))
    text, blocks = _blocks_from_lines(lines)
    return _result_from_blocks(text, blocks, source_name, "docx")


# --- ODT ---------------------------------------------------------------------
_TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


@register(".odt")
def ingest_odt(raw: bytes, source_name: str) -> IngestResult:
    try:
        with zipfile.ZipFile(_bytes_io(raw)) as zf:
            xml = zf.read("content.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise UnsupportedFormat(f"not a readable .odt ({exc})") from exc
    root = ET.fromstring(xml)
    lines: list[tuple[str, int]] = []
    for elem in root.iter():
        tag = elem.tag
        if tag == f"{_TEXT_NS}h":
            level = int(elem.get(f"{_TEXT_NS}outline-level", "1") or "1")
            lines.append(("".join(elem.itertext()), min(level, 6)))
        elif tag == f"{_TEXT_NS}p":
            content = "".join(elem.itertext())
            if content.strip():
                lines.append((content, 0))
    text, blocks = _blocks_from_lines(lines)
    return _result_from_blocks(text, blocks, source_name, "odt")


# --- RTF ---------------------------------------------------------------------
_RTF_CTRL = re.compile(r"\\([a-zA-Z]+)-?\d* ?|\\'[0-9a-fA-F]{2}|[{}]|\r?\n")


@register(".rtf")
def ingest_rtf(raw: bytes, source_name: str) -> IngestResult:
    body = raw.decode("latin-1", errors="ignore")
    # Paragraph breaks from \par / \pard, then strip remaining control words.
    body = re.sub(r"\\par[d]?\b", "\n", body)
    text_only = _RTF_CTRL.sub("", body)
    lines = [(ln, 0) for ln in text_only.split("\n")]
    text, blocks = _blocks_from_lines(lines)
    return _result_from_blocks(text, blocks, source_name, "rtf")


# --- EPUB --------------------------------------------------------------------
@register(".epub")
def ingest_epub(raw: bytes, source_name: str) -> IngestResult:
    try:
        with zipfile.ZipFile(_bytes_io(raw)) as zf:
            names = sorted(
                n for n in zf.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))
            )
            htmls = [zf.read(n).decode("utf-8", errors="surrogateescape") for n in names]
    except zipfile.BadZipFile as exc:
        raise UnsupportedFormat(f"not a readable .epub ({exc})") from exc
    lines: list[tuple[str, int]] = []
    for html in htmls:
        lines.extend(_html_to_lines(html))
    text, blocks = _blocks_from_lines(lines)
    return _result_from_blocks(text, blocks, source_name, "epub")


# --- PDF (optional extra) ----------------------------------------------------
@register(".pdf")
def ingest_pdf(raw: bytes, source_name: str) -> IngestResult:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise UnsupportedFormat(
            "PDF ingestion needs an extra: install 'textgraph[ingest]'"
        ) from exc
    reader = PdfReader(_bytes_io(raw))
    lines: list[tuple[str, int]] = []
    for page in reader.pages:
        for para in (page.extract_text() or "").split("\n\n"):
            if para.strip():
                lines.append((para, 0))
    text, blocks = _blocks_from_lines(lines)
    return _result_from_blocks(text, blocks, source_name, "pdf")


def _bytes_io(raw: bytes) -> io.BytesIO:
    return io.BytesIO(raw)
