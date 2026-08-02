"""L1 — Deterministic Structure Parse (the real tree-sitter moment).

Zero models. Walks each document's block tree and inline text to emit a structural
spine: sections, chunks, links, definitions, citations, cross-references, rationale
and requirement nodes, transcript threads, log templates, and structured fields.
Every edge is ``STRUCTURAL`` (confidence 1.0) with a re-verifiable source span.

Inline patterns are scanned over the *canonical source slice* of each block (not
the rendered inline text) so offsets stay exact relative to the raw bytes.
"""

from __future__ import annotations

import re

from textgraph.core.content_address import hash_text
from textgraph.core.layout import Block, BlockKind, IngestResult, Span
from textgraph.l1_structure.emit import edge, node, normalize_key, source_span
from textgraph.store.base import Edge, Node

# --- inline patterns ---------------------------------------------------------
_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
_MDLINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_URL = re.compile(r"(?<![\(<\[])\bhttps?://[^\s)\]<>]+")
_CITATION = re.compile(r"\[(\d{1,3})\]")
_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
_ARXIV = re.compile(r"\barXiv:\d{4}\.\d{4,5}\b", re.IGNORECASE)
_XREF = re.compile(r"§\s?\d+(?:\.\d+)*|\b(?:Table|Figure|Fig\.|Section|Appendix)\s+\d+\b")
_DEFINITION = re.compile(r"^\s*([A-Z][A-Za-z0-9 /\-]{1,48}):[ \t]+(\S.{2,})$")
_RATIONALE = re.compile(
    r"\b(WHY|DECISION|RATIONALE|TODO|ACTION|NOTE|CONTEXT|CONSEQUENCES?|WHEREAS)\b:?"
    r"|\bADR[- ]?\d+\b"
)
_RFC2119 = re.compile(
    r"\b(MUST NOT|MUST|SHALL NOT|SHALL|SHOULD NOT|SHOULD|REQUIRED|RECOMMENDED|MAY|OPTIONAL)\b"
)
# Keywords that look like definitions but are really markers/roles.
_DEF_STOPWORDS = frozenset(
    {
        "why",
        "decision",
        "todo",
        "action",
        "note",
        "context",
        "rationale",
        "status",
        "consequences",
        "consequence",
        "whereas",
        "warning",
        "error",
        "info",
        "debug",
    }
)

_INLINE_KINDS = {BlockKind.HEADING, BlockKind.PARAGRAPH, BlockKind.LIST_ITEM, BlockKind.QUOTE}


class L1Parser:
    """Accumulates deterministic nodes/edges across a corpus of IngestResults."""

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}

    # -- collection helpers --
    def _add_node(self, n: Node) -> None:
        self._nodes.setdefault(n.node_id, n)

    def _add_edge(self, e: Edge) -> None:
        self._edges.setdefault(e.edge_id, e)

    def result(self) -> tuple[list[Node], list[Edge]]:
        nodes = sorted(self._nodes.values(), key=lambda n: n.node_id)
        edges = sorted(self._edges.values(), key=lambda e: e.edge_id)
        return nodes, edges

    # -- main entry --
    def parse(self, ir: IngestResult) -> None:
        doc_id = f"doc:{ir.doc_id}"
        self._add_node(
            node(
                doc_id,
                "Document",
                ir.source_name,
                path=ir.source_path,
                format=ir.format,
                lang=ir.lang,
            )
        )

        stack: list[tuple[int, str]] = []  # (heading level, section_id)
        heading_pos: list[tuple[int, str]] = []
        prev_message: str | None = None
        log_templates: dict[str, tuple[int, Span]] = {}  # template -> (count, first span)

        ordered: list[Block] = [b for top in ir.blocks for b in top.walk()]
        for b in ordered:
            owner = stack[-1][1] if stack else doc_id

            if b.kind is BlockKind.HEADING:
                sid = "section:" + hash_text(f"{ir.doc_id}|{b.span.start}|{b.span.end}|{b.text}")
                self._add_node(node(sid, "Section", b.text, level=b.level))
                while stack and stack[-1][0] >= b.level:
                    stack.pop()
                parent = stack[-1][1] if stack else doc_id
                self._add_edge(edge(parent, "CONTAINS", sid, source_span(ir, b.span)))
                stack.append((b.level, sid))
                heading_pos.append((b.span.start, sid))
                owner = sid

            if b.kind in _INLINE_KINDS:
                self._scan_inline(ir, b, owner)
            elif b.kind is BlockKind.FIELD:
                self._emit_field(ir, b, doc_id)
            elif b.kind is BlockKind.TRANSCRIPT_TURN:
                prev_message = self._emit_turn(ir, b, doc_id, prev_message)
                # Chat messages carry rationale/requirements/links too, but the
                # "Speaker:" prefix must not be mistaken for a definition.
                self._scan_inline(ir, b, prev_message, include_definitions=False)
            elif b.kind is BlockKind.LOG_LINE:
                tpl = str(b.props.get("template", ""))
                count, first = log_templates.get(tpl, (0, b.span))
                log_templates[tpl] = (count + 1, first)

        self._emit_logs(ir, doc_id, log_templates)
        self._emit_chunks(ir, doc_id, heading_pos)

    # -- inline signal extraction --
    def _scan_inline(
        self, ir: IngestResult, b: Block, owner: str, *, include_definitions: bool = True
    ) -> None:
        text = ir.text
        src = text[b.span.start : b.span.end]
        base = b.span.start

        def span_at(m: re.Match[str]) -> Span:
            return Span(base + m.start(), base + m.end())

        def line_around(pos: int) -> str:
            """The single source line containing offset ``pos`` (for tidy names)."""
            left = src.rfind("\n", 0, pos) + 1
            right = src.find("\n", pos)
            right = len(src) if right == -1 else right
            return src[left:right].strip()[:160]

        for m in _WIKILINK.finditer(src):
            target = m.group(1).strip()
            tid = "ref:" + normalize_key(target)
            self._add_node(node(tid, "Reference", target, kind="wikilink"))
            self._add_edge(edge(owner, "LINKS_TO", tid, source_span(ir, span_at(m))))
        for m in _MDLINK.finditer(src):
            url = m.group(2).strip()
            tid = "ref:" + normalize_key(url)
            self._add_node(node(tid, "Reference", url, kind="link", link_text=m.group(1).strip()))
            self._add_edge(edge(owner, "LINKS_TO", tid, source_span(ir, span_at(m))))
        for m in _URL.finditer(src):
            url = m.group(0).strip().rstrip(".,);")
            tid = "ref:" + normalize_key(url)
            self._add_node(node(tid, "Reference", url, kind="url"))
            self._add_edge(edge(owner, "LINKS_TO", tid, source_span(ir, span_at(m))))
        for m in _CITATION.finditer(src):
            cid = f"cite:{ir.doc_id}:{m.group(1)}"
            self._add_node(node(cid, "Citation", f"[{m.group(1)}]"))
            self._add_edge(edge(owner, "CITES", cid, source_span(ir, span_at(m))))
        for pattern, kind in ((_DOI, "doi"), (_ARXIV, "arxiv")):
            for m in pattern.finditer(src):
                wid = f"ref:{kind}:" + normalize_key(m.group(0))
                self._add_node(node(wid, "Work", m.group(0).strip(), kind=kind))
                self._add_edge(edge(owner, "CITES", wid, source_span(ir, span_at(m))))
        for m in _XREF.finditer(src):
            xid = f"xref:{ir.doc_id}:" + normalize_key(m.group(0))
            self._add_node(node(xid, "CrossRef", m.group(0).strip()))
            self._add_edge(edge(owner, "REFERENCES", xid, source_span(ir, span_at(m))))
        for m in _RATIONALE.finditer(src):
            rid = "rationale:" + hash_text(f"{ir.doc_id}|{base + m.start()}")
            self._add_node(
                node(rid, "Rationale", line_around(m.start()), marker=m.group(0).strip())
            )
            self._add_edge(edge(rid, "APPLIES_TO", owner, source_span(ir, b.span)))
        for m in _RFC2119.finditer(src):
            qid = "requirement:" + hash_text(f"{ir.doc_id}|{base + m.start()}")
            self._add_node(
                node(qid, "Requirement", line_around(m.start()), keyword=m.group(0).strip())
            )
            self._add_edge(edge(owner, "STATES_REQUIREMENT", qid, source_span(ir, span_at(m))))

        if not include_definitions:
            return
        dm = _DEFINITION.match(src)
        if dm and normalize_key(dm.group(1)) not in _DEF_STOPWORDS:
            term = dm.group(1).strip()
            tid = "term:" + normalize_key(term)
            self._add_node(node(tid, "Term", term))
            self._add_edge(edge(f"doc:{ir.doc_id}", "DEFINES", tid, source_span(ir, b.span)))

    def _emit_field(self, ir: IngestResult, b: Block, doc_id: str) -> None:
        path = str(b.props.get("path", ""))
        fid = "field:" + hash_text(f"{ir.doc_id}|{path}")
        self._add_node(node(fid, "Field", path, value=str(b.props.get("value", ""))))
        self._add_edge(edge(doc_id, "HAS_FIELD", fid, source_span(ir, b.span)))

    def _emit_turn(self, ir: IngestResult, b: Block, doc_id: str, prev_message: str | None) -> str:
        speaker = str(b.props.get("speaker", ""))
        pid = "participant:" + normalize_key(speaker)
        mid = "message:" + hash_text(f"{ir.doc_id}|{b.span.start}")
        self._add_node(node(pid, "Participant", speaker))
        self._add_node(
            node(
                mid,
                "Message",
                str(b.props.get("message", ""))[:200],
                speaker=speaker,
                timestamp=str(b.props.get("timestamp", "")),
            )
        )
        sp = source_span(ir, b.span)
        self._add_edge(edge(pid, "PARTICIPANT", doc_id, sp))
        self._add_edge(edge(mid, "SENT_BY", pid, sp))
        if prev_message is not None:
            self._add_edge(edge(mid, "REPLIES_TO", prev_message, sp))
        return mid

    def _emit_logs(
        self, ir: IngestResult, doc_id: str, templates: dict[str, tuple[int, Span]]
    ) -> None:
        for tpl, (count, first) in templates.items():
            lid = "logtpl:" + hash_text(tpl)
            self._add_node(node(lid, "LogTemplate", tpl, occurrences=count))
            e = edge(doc_id, "EMITS", lid, source_span(ir, first))
            self._add_edge(
                Edge(
                    edge_id=e.edge_id,
                    subject=e.subject,
                    predicate=e.predicate,
                    object=e.object,
                    tag=e.tag,
                    confidence=e.confidence,
                    evidence_count=count,
                    source_spans=e.source_spans,
                    properties=e.properties,
                )
            )

    def _emit_chunks(
        self, ir: IngestResult, doc_id: str, heading_pos: list[tuple[int, str]]
    ) -> None:
        positions = sorted(heading_pos)
        for ch in ir.chunks:
            self._add_node(
                node(
                    ch.chunk_id,
                    "Chunk",
                    "/".join(ch.breadcrumb) or ir.source_name,
                    token_count=ch.token_count,
                    layout_type=str(ch.layout_type),
                    index=ch.index,
                )
            )
            parent = doc_id
            for start, sid in positions:
                if start <= ch.span.start:
                    parent = sid
                else:
                    break
            self._add_edge(edge(parent, "CONTAINS", ch.chunk_id, source_span(ir, ch.span)))


def parse_corpus(results: list[IngestResult]) -> tuple[list[Node], list[Edge]]:
    """Run L1 over every ingested document; returns sorted nodes and edges."""
    parser = L1Parser()
    for ir in sorted(results, key=lambda r: r.doc_id):
        parser.parse(ir)
    return parser.result()
