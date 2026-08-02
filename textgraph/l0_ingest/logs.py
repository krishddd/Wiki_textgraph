"""Log ingestor (L0): lightweight deterministic template mining.

A dependency-free stand-in for Drain3 (which lands behind the ``[ingest]`` extra):
each line is masked (numbers, IPs, hex/UUIDs, timestamps, quoted strings ->
``<*>``) to form a template. Identical templates collapse, turning a large log into
a small set of LOG_LINE blocks tagged with their template. Fully deterministic.
"""

from __future__ import annotations

import re

from textgraph.core.layout import Block, BlockKind, IngestResult, Span
from textgraph.l0_ingest.base import canonical_for, make_chunks, register

_MASKS = [
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?\b"), "<TS>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<IP>"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\b"), "<UUID>"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<HEX>"),
    (re.compile(r'"[^"]*"'), "<STR>"),
    (re.compile(r"\b\d+\b"), "<NUM>"),
]


def templatize(line: str) -> str:
    """Return the deterministic template for a log line."""
    out = line
    for pattern, repl in _MASKS:
        out = pattern.sub(repl, out)
    return out.strip()


@register(".log")
def ingest_log(raw: bytes, source_name: str) -> IngestResult:
    canonical = canonical_for(raw, source_name)
    text = canonical.text
    blocks: list[Block] = []
    pos = 0
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        content = stripped.rstrip()
        if content:
            blocks.append(
                Block(
                    BlockKind.LOG_LINE,
                    Span(pos, pos + len(content)),
                    content,
                    props={"template": templatize(content)},
                )
            )
        pos += len(line)
    chunks = make_chunks(canonical.doc_id, text, blocks)
    return IngestResult(
        canonical=canonical,
        raw=raw,
        source_path=source_name,
        format="log",
        blocks=blocks,
        chunks=chunks,
    )
