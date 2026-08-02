"""Plain-text ingestor (L0).

Splits into paragraph blocks on blank lines, preserving exact canonical-char
spans. The fallback for any unknown extension.
"""

from __future__ import annotations

from textgraph.core.layout import Block, BlockKind, IngestResult, Span
from textgraph.l0_ingest.base import canonical_for, make_chunks, register


def _paragraph_blocks(text: str) -> list[Block]:
    blocks: list[Block] = []
    pos = 0
    n = len(text)
    while pos < n:
        # Skip blank lines.
        while pos < n and text[pos] in "\n":
            pos += 1
        if pos >= n:
            break
        start = pos
        # A paragraph runs until a blank line (\n\n) or EOF.
        nl = text.find("\n\n", pos)
        end = n if nl == -1 else nl
        chunk = text[start:end].rstrip()
        real_end = start + len(chunk)
        if chunk:
            blocks.append(Block(BlockKind.PARAGRAPH, Span(start, real_end), chunk))
        pos = end
    return blocks


@register(".txt", ".text")
def ingest_plaintext(raw: bytes, source_name: str) -> IngestResult:
    canonical = canonical_for(raw, source_name)
    text = canonical.text
    blocks = _paragraph_blocks(text)
    chunks = make_chunks(canonical.doc_id, text, blocks)
    return IngestResult(
        canonical=canonical,
        raw=raw,
        source_path=source_name,
        format="plaintext",
        blocks=blocks,
        chunks=chunks,
    )
