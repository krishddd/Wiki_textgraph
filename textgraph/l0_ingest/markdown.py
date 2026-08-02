"""Markdown ingestor (L0).

Uses the real markdown-it-py grammar for *block* structure (headings, paragraphs,
lists, code, quotes, tables) and derives exact canonical-char spans from token
line maps. Inline signals (links, definitions, rationale) are recovered in L1 from
each block's text span. We never regex the block grammar (§3.1).
"""

from __future__ import annotations

from markdown_it import MarkdownIt
from markdown_it.token import Token

from textgraph.core.layout import Block, BlockKind, IngestResult, Span
from textgraph.l0_ingest.base import LineIndex, canonical_for, make_chunks, register

_MD = MarkdownIt("commonmark").enable("table")


def _inline_text(token: Token | None) -> str:
    if token is None or token.children is None:
        return token.content if token else ""
    return "".join(c.content for c in token.children if c.type in ("text", "code_inline"))


def _blocks_from_tokens(tokens: list[Token], line_index: LineIndex) -> list[Block]:
    """Flatten markdown-it's token stream into a document-order block list.

    Container nesting (lists, quotes) is preserved via ``Block.children`` so the
    heading/section hierarchy and chunk breadcrumbs come out right.
    """
    root: list[Block] = []
    stack: list[Block] = []

    def emit(block: Block) -> None:
        if stack:
            stack[-1].children.append(block)
        else:
            root.append(block)

    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        span = line_index.span_for_lines(*tok.map) if tok.map else Span(0, 0)

        if tok.type == "heading_open":
            inline = tokens[i + 1] if i + 1 < n else None
            level = int(tok.tag[1:]) if tok.tag[1:].isdigit() else 1
            emit(Block(BlockKind.HEADING, span, _inline_text(inline).strip(), level=level))
            i += 3  # heading_open, inline, heading_close
            continue
        if tok.type == "paragraph_open":
            inline = tokens[i + 1] if i + 1 < n else None
            emit(Block(BlockKind.PARAGRAPH, span, _inline_text(inline)))
            i += 3
            continue
        if tok.type in ("fence", "code_block"):
            emit(Block(BlockKind.CODE, span, tok.content, props={"info": tok.info}))
            i += 1
            continue
        if tok.type in ("blockquote_open", "bullet_list_open", "ordered_list_open"):
            kind = BlockKind.QUOTE if "blockquote" in tok.type else BlockKind.LIST_ITEM
            container = Block(kind, span, "")
            emit(container)
            stack.append(container)
            i += 1
            continue
        if tok.type in ("blockquote_close", "bullet_list_close", "ordered_list_close"):
            if stack:
                stack.pop()
            i += 1
            continue
        if tok.type == "list_item_open":
            item = Block(BlockKind.LIST_ITEM, span, "")
            emit(item)
            stack.append(item)
            i += 1
            continue
        if tok.type == "list_item_close":
            if stack:
                stack.pop()
            i += 1
            continue
        if tok.type == "table_open":
            emit(Block(BlockKind.TABLE, span, ""))
            i += 1
            continue
        i += 1

    return root


@register(".md", ".markdown", ".mdx")
def ingest_markdown(raw: bytes, source_name: str) -> IngestResult:
    canonical = canonical_for(raw, source_name)
    text = canonical.text
    line_index = LineIndex(text)
    tokens = _MD.parse(text)
    blocks = _blocks_from_tokens(tokens, line_index)
    chunks = make_chunks(canonical.doc_id, text, blocks)
    return IngestResult(
        canonical=canonical,
        raw=raw,
        source_path=source_name,
        format="markdown",
        blocks=blocks,
        chunks=chunks,
    )
