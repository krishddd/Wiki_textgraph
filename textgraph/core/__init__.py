"""Core primitives shared by every layer: content addressing, offset maps,
canonical serialization, CanonicalDoc, and pinned config hashing.

These underpin the non-negotiable design goals:
  G1 (determinism)  -> canonical_json + config hashing
  G3 (provenance)   -> content_address + offsets + CanonicalDoc.raw_span
  G5 (incrementality)-> content_address (blake3 content-addressed chunks)
"""

from textgraph.core.canonical_doc import CanonicalDoc, normalize
from textgraph.core.canonical_json import canonical_dump_bytes, canonical_dumps
from textgraph.core.config import Config
from textgraph.core.content_address import DOC_ID_PREFIX, blake3_hex, doc_id_for
from textgraph.core.offsets import OffsetMap, OffsetRun

__all__ = [
    "DOC_ID_PREFIX",
    "CanonicalDoc",
    "Config",
    "OffsetMap",
    "OffsetRun",
    "blake3_hex",
    "canonical_dump_bytes",
    "canonical_dumps",
    "doc_id_for",
    "normalize",
]
