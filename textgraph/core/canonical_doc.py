"""CanonicalDoc + normalization (L0 primitive).

Normalization decodes raw bytes into canonical UTF-8 text and builds an
:class:`OffsetMap` so any canonical char span can be mapped back to the exact raw
byte range that produced it. This is the L0 contract every later layer relies on:
canonical text to reason over, plus a re-verifiable path back to source bytes (G3).

Phase 0 normalization is intentionally minimal and lossless-to-provenance:
  * decode UTF-8 (strict; a BOM, if present, is stripped and accounted for),
  * collapse CRLF and lone CR to a single LF.

Richer, format-aware ingestion (Docling, tree-sitter, ...) lands in L0 proper in
Phase 1 and produces CanonicalDoc the same way, so the interface is stable now.
"""

from __future__ import annotations

from dataclasses import dataclass

from textgraph.core.content_address import blake3_hex, doc_id_for
from textgraph.core.offsets import OffsetMap

_BOM = "﻿"


def _byte_len(chars: str, encoding: str) -> int:
    """Raw-byte length of ``chars`` under ``encoding``, surrogate-safe.

    A lone surrogate produced by the surrogateescape decode re-encodes to exactly
    the one original byte it stood for; a normal character to its usual width.
    """
    return len(chars.encode(encoding, errors="surrogateescape"))


def normalize(raw: bytes, *, encoding: str = "utf-8") -> tuple[str, OffsetMap]:
    """Return ``(canonical_text, offset_map)`` for ``raw`` bytes.

    The offset map records, per canonical character, how many raw bytes it
    consumed, so ``offset_map.to_raw_span`` recovers the original byte range.
    Deterministic: identical bytes always produce identical output (G1).
    """
    # Decode with surrogateescape so undecodable bytes (OCR output, mixed-encoding
    # logs, binary-ish content — all in the L0 format matrix) each map to one lone
    # surrogate code point instead of crashing. Re-encoding a surrogate with the
    # same codec reproduces the exact original byte, so offset fidelity and
    # provenance (G3) stay exact, and the transform stays deterministic (G1).
    text = raw.decode(encoding, errors="surrogateescape")

    canonical_chars: list[str] = []
    byte_lengths: list[int] = []

    # Strip a single leading BOM, recording the raw bytes it consumed so the first
    # canonical character still maps to its true raw offset. A BOM appearing mid-
    # document is a (deprecated) zero-width no-break space and is kept verbatim.
    raw_start = 0
    i = 0
    n = len(text)
    if n and text[0] == _BOM:
        raw_start = _byte_len(_BOM, encoding)
        i = 1

    while i < n:
        ch = text[i]

        if ch == "\r":
            # Collapse CRLF or a lone CR into a single LF. The canonical '\n'
            # consumes either 2 raw bytes (CRLF) or 1 (lone CR).
            if i + 1 < n and text[i + 1] == "\n":
                canonical_chars.append("\n")
                byte_lengths.append(_byte_len("\r\n", encoding))
                i += 2
            else:
                canonical_chars.append("\n")
                byte_lengths.append(_byte_len("\r", encoding))
                i += 1
            continue

        canonical_chars.append(ch)
        byte_lengths.append(_byte_len(ch, encoding))
        i += 1

    canonical = "".join(canonical_chars)
    offset_map = OffsetMap.from_char_byte_lengths(
        byte_lengths, raw_len=len(raw), raw_start=raw_start
    )
    return canonical, offset_map


@dataclass(frozen=True)
class CanonicalDoc:
    """A normalized document plus everything needed to cite back to raw bytes.

    Attributes:
        doc_id: ``blake3:<hex>`` of the raw bytes (content-addressed identity).
        text: canonical UTF-8 normalized text.
        offset_map: canonical-char -> raw-byte mapping.
        raw_len: length of the original raw bytes.
        source_name: optional human-facing origin (path, url, ...); not part of identity.
    """

    doc_id: str
    text: str
    offset_map: OffsetMap
    raw_len: int
    source_name: str | None = None

    @classmethod
    def from_bytes(
        cls, raw: bytes, *, source_name: str | None = None, encoding: str = "utf-8"
    ) -> CanonicalDoc:
        text, offset_map = normalize(raw, encoding=encoding)
        return cls(
            doc_id=doc_id_for(raw),
            text=text,
            offset_map=offset_map,
            raw_len=len(raw),
            source_name=source_name,
        )

    def raw_span(self, start: int, end: int) -> tuple[int, int]:
        """Map a canonical char span ``[start, end)`` to a raw byte span."""
        return self.offset_map.to_raw_span(start, end)

    def span_hash(self, raw: bytes, start: int, end: int) -> str:
        """Hash the raw bytes underlying canonical span ``[start, end)``.

        The value returned here is what gets stored in ``source_spans[*].hash`` and
        later re-verified against the original bytes (G3).
        """
        b0, b1 = self.raw_span(start, end)
        return blake3_hex(raw[b0:b1])
