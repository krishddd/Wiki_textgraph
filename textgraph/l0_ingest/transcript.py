"""Transcript / chat-export ingestor (L0).

Parses ``Speaker: message`` turn lines (optionally with a leading ``[timestamp]``)
into TRANSCRIPT_TURN blocks carrying the speaker. L1 turns these into Message and
Participant nodes with REPLIES_TO / PARTICIPANT edges. Registered for ``.chat`` and
``.transcript``; plain ``.txt`` chat logs can be pointed here explicitly.
"""

from __future__ import annotations

import re

from textgraph.core.layout import Block, BlockKind, IngestResult, Span
from textgraph.l0_ingest.base import canonical_for, make_chunks, register

# [2026-08-01 10:00] Alice: hello   |   Alice: hello
_TURN = re.compile(r"^(?:\[(?P<ts>[^\]]+)\]\s*)?(?P<speaker>[^:\n]{1,40}):\s(?P<msg>.*)$")


@register(".chat", ".transcript")
def ingest_transcript(raw: bytes, source_name: str) -> IngestResult:
    canonical = canonical_for(raw, source_name)
    text = canonical.text
    blocks: list[Block] = []
    pos = 0
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        m = _TURN.match(stripped)
        if m and stripped.strip():
            content = stripped.rstrip()
            blocks.append(
                Block(
                    BlockKind.TRANSCRIPT_TURN,
                    Span(pos, pos + len(content)),
                    content.rstrip(),
                    props={
                        "speaker": m.group("speaker").strip(),
                        "timestamp": (m.group("ts") or "").strip(),
                        "message": m.group("msg").strip(),
                    },
                )
            )
        pos += len(line)
    chunks = make_chunks(canonical.doc_id, text, blocks)
    return IngestResult(
        canonical=canonical,
        raw=raw,
        source_path=source_name,
        format="transcript",
        blocks=blocks,
        chunks=chunks,
    )
