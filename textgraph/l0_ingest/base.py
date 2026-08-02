"""L0 ingestion base: line index, token counting, chunking, and the registry.

Every ingestor is a pure function ``bytes -> IngestResult`` (deterministic, G1).
Chunking is hierarchical and heading-aware (never fixed-size windows, §3.3).
"""

from __future__ import annotations

import re
from collections.abc import Callable

from textgraph.core.canonical_doc import CanonicalDoc
from textgraph.core.content_address import blake3_hex
from textgraph.core.layout import Block, BlockKind, Chunk, IngestResult, Span


class UnsupportedFormat(RuntimeError):
    """Raised when a format needs an optional extra that isn't installed.

    Callers (the pipeline) skip the file and record a warning rather than crashing,
    so the default install stays functional (G2).
    """


_WORD = re.compile(r"\S+")

# Chunk when the accumulated block text reaches this many approximate tokens.
CHUNK_TARGET_TOKENS = 600


def count_tokens(text: str) -> int:
    """Deterministic approximate token count (whitespace-delimited words)."""
    return len(_WORD.findall(text))


class LineIndex:
    """Maps 0-indexed line ranges (markdown-it ``token.map``) to canonical spans."""

    __slots__ = ("_starts", "_text_len")

    def __init__(self, text: str) -> None:
        starts = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                starts.append(i + 1)
        # Sentinel so an exclusive end line maps to end-of-text.
        starts.append(len(text))
        self._starts = starts
        self._text_len = len(text)

    def span_for_lines(self, start_line: int, end_line: int) -> Span:
        """Span for the half-open line range ``[start_line, end_line)``.

        May include a trailing newline; that is still a valid, re-verifiable byte
        range, and block text is carried separately, so spans stay exact for
        provenance without fragile trimming.
        """
        n = len(self._starts) - 1
        start_line = max(0, min(start_line, n))
        end_line = max(start_line, min(end_line, n))
        start = self._starts[start_line]
        end = min(self._starts[end_line], self._text_len)
        return Span(start, end)


def make_chunks(
    doc_id: str,
    text: str,
    blocks: list[Block],
    *,
    target_tokens: int = CHUNK_TARGET_TOKENS,
) -> list[Chunk]:
    """Build hierarchical, heading-aware chunks from a flat/branching block tree.

    Walks blocks in document order, tracks a heading stack for the breadcrumb, and
    accumulates non-heading blocks until the token budget is reached or a heading
    boundary is crossed. Chunks are stored non-overlapping (§3.3).
    """
    ordered: list[Block] = []
    for top in blocks:
        ordered.extend(top.walk())

    heading_stack: list[tuple[int, str]] = []  # (level, title)
    chunks: list[Chunk] = []
    pending: list[Block] = []
    pending_tokens = 0
    index = 0

    def breadcrumb() -> tuple[str, ...]:
        return tuple(title for _level, title in heading_stack)

    def flush() -> None:
        nonlocal pending, pending_tokens, index
        if not pending:
            return
        start = min(b.span.start for b in pending)
        end = max(b.span.end for b in pending)
        crumb = breadcrumb()
        chunk_text = text[start:end]
        chunk_id = "chunk:" + blake3_hex(f"{doc_id}|{start}|{end}|{'/'.join(crumb)}".encode())
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                doc_id=doc_id,
                breadcrumb=crumb,
                span=Span(start, end),
                text=chunk_text,
                token_count=count_tokens(chunk_text),
                layout_type=pending[0].kind,
                index=index,
            )
        )
        index += 1
        pending = []
        pending_tokens = 0

    for block in ordered:
        if block.kind is BlockKind.DOCUMENT:
            continue
        if block.kind is BlockKind.HEADING:
            flush()
            while heading_stack and heading_stack[-1][0] >= block.level:
                heading_stack.pop()
            heading_stack.append((block.level, block.text.strip()))
            continue
        block_tokens = count_tokens(block.text)
        if pending and pending_tokens + block_tokens > target_tokens:
            flush()
        pending.append(block)
        pending_tokens += block_tokens

    flush()
    return chunks


# --- Ingestor registry -------------------------------------------------------

Ingestor = Callable[[bytes, str], IngestResult]

_REGISTRY: dict[str, Ingestor] = {}


def register(*extensions: str) -> Callable[[Ingestor], Ingestor]:
    """Register an ingestor for one or more lowercase file extensions."""

    def deco(fn: Ingestor) -> Ingestor:
        for ext in extensions:
            _REGISTRY[ext.lower()] = fn
        return fn

    return deco


def get_ingestor(extension: str) -> Ingestor | None:
    return _REGISTRY.get(extension.lower())


def registered_extensions() -> list[str]:
    return sorted(_REGISTRY)


def canonical_for(raw: bytes, source_name: str) -> CanonicalDoc:
    """Byte-preserving canonical doc: canonical text derives from ``raw`` bytes.

    Used for formats whose source *is* the text (md, txt, logs, json/yaml, ...);
    provenance cites the original file bytes.
    """
    return CanonicalDoc.from_bytes(raw, source_name=source_name)


def canonical_from_text(text: str, source_name: str) -> tuple[CanonicalDoc, bytes]:
    """Derived-text canonical doc for rich formats (docx/pdf/odt/epub/rtf/html).

    Their extracted plain text is *not* a substring of the original binary, so the
    extracted text (UTF-8) becomes the canonical document: ``doc_id`` content-
    addresses the extracted text and provenance spans re-verify against it. The
    original file's hash is recorded separately by the ingestor for reference.
    """
    raw = text.encode("utf-8")
    return CanonicalDoc.from_bytes(raw, source_name=source_name), raw
