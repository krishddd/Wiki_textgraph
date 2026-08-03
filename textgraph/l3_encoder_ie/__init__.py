"""L3 — Encoder Information Extraction.

Turns text into typed entities and relations. The default backend is a
deterministic, zero-model rule extractor (CPU-only, CI-safe); ``backend="gliner"``
selects the GLiNER encoder behind the ``[ie]`` extra. See ARCHITECTURE.md.
"""

from __future__ import annotations

from textgraph.core.layout import Block
from textgraph.l3_encoder_ie.emit_ie import emit_ie
from textgraph.l3_encoder_ie.extract import extract_document
from textgraph.l3_encoder_ie.model import IEResult

__all__ = ["IEResult", "emit_ie", "extract_document", "run_ie"]


def run_ie(text: str, *, blocks: list[Block] | None = None, backend: str = "rules") -> IEResult:
    """Extract entities + relations from ``text`` using the chosen backend.

    ``blocks`` (from L0) confine entity/sentence detection to prose blocks so an
    entity never spans a heading→paragraph boundary. ``backend='rules'`` (default)
    is deterministic and model-free; ``backend='gliner'`` requires ``textgraph[ie]``.
    """
    if backend == "gliner":
        from textgraph.l3_encoder_ie.gliner_backend import extract_document_gliner

        return extract_document_gliner(text)
    return extract_document(text, blocks)
