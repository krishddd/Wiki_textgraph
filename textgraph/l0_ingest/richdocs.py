"""Rich-document ingestors (L0): HTML, DOCX, ODT, RTF, EPUB, PDF.

These formats do not store their text as a byte-substring of the file, so the
*extracted* plain text becomes the canonical document (see ``canonical_from_text``)
and provenance spans re-verify against that extracted text. Structure (headings vs
paragraphs) is recovered deterministically from each format's native markup:

  * HTML/XHTML/EPUB  -> stdlib ``html.parser`` (heading tags, paragraphs, lists)
  * DOCX/ODT         -> stdlib ``zipfile`` + XML (paragraph styles / outline levels)
  * RTF              -> control-word stripping into paragraphs
  * PDF              -> ``pypdf`` (a core dependency; extracts the text layer). Layout/OCR
                        fidelity for scanned or complex PDFs is the opt-in ``[ingest]`` extra.

All use stdlib except PDF (pypdf, a small pure-Python core dep). Everything is deterministic (G1).
"""

from __future__ import annotations

import io
import re
import zipfile
from html.parser import HTMLParser
from typing import Any
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


# --- PDF (text layer; pypdf is a core dependency) ----------------------------
def _pdf_blocks(page_texts: list[str]) -> tuple[str, list[Block], tuple[tuple[int, int], ...]]:
    """Assemble canonical text + span-carrying blocks + a page map from per-page text.

    Pure and deterministic (no pypdf dependency here, so it's unit-testable): each page's
    paragraphs become ``PARAGRAPH`` blocks stamped with their 1-based ``page`` prop, and the
    page map records the canonical-char offset where each non-empty page's text begins — so a
    citation anywhere in that page resolves to the right page number (blank pages are skipped
    but their true page number is preserved via the map, never renumbered).
    """
    parts: list[str] = []
    blocks: list[Block] = []
    page_map: list[tuple[int, int]] = []
    pos = 0
    for page_no, page_text in enumerate(page_texts, start=1):
        paras = [p.strip() for p in (page_text or "").split("\n\n") if p.strip()]
        if not paras:
            continue
        page_map.append((pos, page_no))
        for content in paras:
            start = pos
            end = start + len(content)
            blocks.append(
                Block(BlockKind.PARAGRAPH, Span(start, end), content, props={"page": page_no})
            )
            parts.append(content)
            pos = end + 2  # account for the "\n\n" separator we join with
    return "\n\n".join(parts), blocks, tuple(page_map)


_Frag = tuple[str, float, float, float, float]  # (text, x0, y0, x1, y1) in PDF points


def _nonspace_len(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def _union(boxes: list[_Frag]) -> tuple[float, float, float, float]:
    """Bounding box enclosing every fragment box (ignores the leading text field)."""
    xs0 = [b[1] for b in boxes]
    ys0 = [b[2] for b in boxes]
    xs1 = [b[3] for b in boxes]
    ys1 = [b[4] for b in boxes]
    return (min(xs0), min(ys0), max(xs1), max(ys1))


def _attach_bboxes(
    block_texts: list[str], fragments: list[_Frag]
) -> list[tuple[float, float, float, float] | None]:
    """Align each block on a page to a bounding box by sequential fragment consumption.

    Pure and deterministic (no pypdf here, so it's unit-testable): ``extract_text`` and the
    positioned ``fragments`` both traverse the page's content stream in the same order, so we
    walk the fragments once, handing each block enough fragments to cover its non-whitespace
    character count and taking the union of their boxes. Blocks with no covering fragment (e.g.
    a page with no text layer) get ``None`` — page-only provenance, never a wrong box.
    """
    out: list[tuple[float, float, float, float] | None] = []
    i = 0
    n = len(fragments)
    for text in block_texts:
        target = _nonspace_len(text)
        taken: list[_Frag] = []
        got = 0
        while i < n and got < target:
            frag = fragments[i]
            taken.append(frag)
            got += _nonspace_len(frag[0])
            i += 1
        out.append(_union(taken) if taken else None)
    return out


def _build_bbox_map(
    blocks: list[Block], page_fragments: list[list[_Frag]]
) -> tuple[tuple[int, tuple[float, float, float, float]], ...]:
    """Map each block's canonical-char start to its bounding box, grouped by page.

    ``page_fragments`` is indexed by 0-based page index; blocks carry their 1-based ``page``
    prop, so a block on page P is aligned against ``page_fragments[P-1]``.
    """
    by_page: dict[int, list[Block]] = {}
    for b in blocks:
        pg = b.props.get("page", 0)
        by_page.setdefault(pg if isinstance(pg, int) else 0, []).append(b)
    entries: list[tuple[int, tuple[float, float, float, float]]] = []
    for page_no, page_blocks in by_page.items():
        frags = page_fragments[page_no - 1] if 1 <= page_no <= len(page_fragments) else []
        boxes = _attach_bboxes([b.text for b in page_blocks], frags)
        for block, box in zip(page_blocks, boxes, strict=True):
            if box is not None:
                entries.append((block.span.start, box))
    return tuple(sorted(entries, key=lambda e: e[0]))


def _origin(tm: list[float], cm: list[float]) -> tuple[float, float]:
    """Device-space (x, y) origin of a text fragment: the composition ``tm ∘ cm``."""
    x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
    y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
    return x, y


def _extract_page(page: Any) -> tuple[str, list[_Frag], tuple[float, float]]:
    """Extract a page's text, its positioned fragments, and its (width, height) in one pass.

    The ``visitor_text`` callback runs *during* ``extract_text``, so the returned text keeps
    pypdf's proven segmentation while the fragments capture each run's box (origin + rough
    advance, in PDF points). Defined at module scope (not a per-page closure) so it's fully
    typed and never captures a loop variable. The page size comes from the MediaBox.
    """
    frags: list[_Frag] = []

    def visit(text: str, cm: list[float], tm: list[float], _fd: object, size: float) -> None:
        if not text or not text.strip():
            return
        x, y = _origin(tm, cm)
        fs = float(size or 0.0)
        w = 0.5 * fs * len(text)  # rough horizontal advance for the box width
        frags.append((text, round(x, 2), round(y, 2), round(x + w, 2), round(y + fs, 2)))

    text = page.extract_text(visitor_text=visit) or ""
    size = (round(float(page.mediabox.width), 2), round(float(page.mediabox.height), 2))
    return text, frags, size


@register(".pdf")
def ingest_pdf(raw: bytes, source_name: str) -> IngestResult:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - pypdf is a core dependency
        raise UnsupportedFormat("PDF ingestion requires pypdf (a core dependency)") from exc
    reader = PdfReader(_bytes_io(raw))
    pages = [_extract_page(page) for page in reader.pages]
    page_texts = [t for t, _f, _s in pages]
    page_fragments = [f for _t, f, _s in pages]
    page_sizes = tuple(s for _t, _f, s in pages)

    text, blocks, page_map = _pdf_blocks(page_texts)
    bbox_map = _build_bbox_map(blocks, page_fragments)
    canonical, raw_bytes = canonical_from_text(text, source_name)
    chunks = make_chunks(canonical.doc_id, text, blocks)
    return IngestResult(
        canonical=canonical,
        raw=raw_bytes,
        source_path=source_name,
        format="pdf",
        blocks=blocks,
        chunks=chunks,
        page_map=page_map,
        bbox_map=bbox_map,
        page_sizes=page_sizes,
    )


def _bytes_io(raw: bytes) -> io.BytesIO:
    return io.BytesIO(raw)
