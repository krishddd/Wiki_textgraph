"""L0 — Ingestion & Normalization.

Turns any textual container into an :class:`~textgraph.core.layout.IngestResult`:
a CanonicalDoc (UTF-8 + offset map) plus a span-carrying block tree and
hierarchical chunks. See ARCHITECTURE.md for the layer contract.
"""

from textgraph.l0_ingest.dispatch import ingest_bytes, ingest_path

__all__ = ["ingest_bytes", "ingest_path"]
