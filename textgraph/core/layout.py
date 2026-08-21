"""Layout model: spans, blocks, block trees, and chunks (L0 output).

L0 turns a document into a tree of :class:`Block`s carrying exact canonical-char
spans, plus hierarchical :class:`Chunk`s. L1 walks the block tree to emit graph
nodes/edges. Spans are canonical-char ranges; provenance maps them to raw bytes
via the doc's offset map, so every span here is re-verifiable (G3).
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from enum import StrEnum

from textgraph.core.canonical_doc import CanonicalDoc


class BlockKind(StrEnum):
    """The structural role of a block, derived deterministically from the format."""

    DOCUMENT = "document"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    CODE = "code"
    TABLE = "table"
    TABLE_ROW = "table_row"
    QUOTE = "quote"
    DEFINITION = "definition"
    TRANSCRIPT_TURN = "transcript_turn"
    FIELD = "field"
    LOG_LINE = "log_line"


@dataclass(frozen=True)
class Span:
    """A canonical-character range ``[start, end)`` within a single document."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"invalid span [{self.start}, {self.end})")


@dataclass
class Block:
    """A structural unit of a document with an exact canonical-char span.

    ``props`` holds kind-specific attributes (e.g. heading ``level``, list depth,
    definition ``term``, transcript ``speaker``, field ``path``).
    """

    kind: BlockKind
    span: Span
    text: str
    level: int = 0
    props: dict[str, object] = field(default_factory=dict)
    children: list[Block] = field(default_factory=list)

    def walk(self) -> list[Block]:
        """Pre-order traversal (deterministic: children in insertion order)."""
        out: list[Block] = [self]
        for child in self.children:
            out.extend(child.walk())
        return out


@dataclass
class Chunk:
    """A hierarchical, heading-aware chunk (retrieval unit; stored non-overlapping)."""

    chunk_id: str
    doc_id: str
    breadcrumb: tuple[str, ...]
    span: Span
    text: str
    token_count: int
    layout_type: BlockKind
    index: int


@dataclass
class IngestResult:
    """Everything L0 produces for one document, consumed by L1.

    ``canonical`` carries the doc id, canonical text, and the offset map; ``raw`` is
    kept so L1 can compute re-verifiable span hashes (G3).
    """

    canonical: CanonicalDoc
    raw: bytes
    source_path: str
    format: str
    blocks: list[Block]
    chunks: list[Chunk]
    lang: str = "en"
    # Optional page provenance for paged sources (PDFs): sorted (canonical_char_start,
    # page_no) boundaries. Empty means unpaged. In-memory only — never serialized into the
    # graph.json doc summary; only the per-citation SourceSpan.page it induces is persisted.
    page_map: tuple[tuple[int, int], ...] = ()
    # Optional per-block bounding boxes: sorted (canonical_char_start, (x0,y0,x1,y1)) in PDF
    # points, one per block that carries layout coordinates. Empty means no bbox info.
    # In-memory only — only the per-citation SourceSpan.bbox it induces is persisted.
    bbox_map: tuple[tuple[int, tuple[float, float, float, float]], ...] = ()
    # Optional per-page (width, height) in PDF points, indexed by 0-based page. Lets a citation
    # carry its page's dimensions so the console can draw the box to scale (clickable-to-region).
    page_sizes: tuple[tuple[float, float], ...] = ()

    @property
    def doc_id(self) -> str:
        return self.canonical.doc_id

    def page_for(self, char_offset: int) -> int:
        """1-based page for a canonical-char offset (0 if this doc carries no page map).

        Deterministic: returns the page of the rightmost boundary at or before ``char_offset``.
        """
        if not self.page_map:
            return 0
        starts = [start for start, _page in self.page_map]
        idx = bisect_right(starts, char_offset) - 1
        if idx < 0:
            return self.page_map[0][1]
        return self.page_map[idx][1]

    def bbox_for(self, char_offset: int) -> tuple[float, float, float, float] | None:
        """Bounding box for the block containing a canonical-char offset (None if unknown).

        Deterministic: returns the bbox of the rightmost block start at or before
        ``char_offset`` (spans emitted downstream always begin inside a block).
        """
        if not self.bbox_map:
            return None
        starts = [start for start, _box in self.bbox_map]
        idx = bisect_right(starts, char_offset) - 1
        if idx < 0:
            return None
        return self.bbox_map[idx][1]

    def page_size_for(self, page_no: int) -> tuple[float, float] | None:
        """(width, height) in PDF points for a 1-based page number (None if unknown)."""
        if 1 <= page_no <= len(self.page_sizes):
            return self.page_sizes[page_no - 1]
        return None

    @property
    def text(self) -> str:
        return self.canonical.text

    @property
    def source_name(self) -> str:
        return self.canonical.source_name or self.source_path
