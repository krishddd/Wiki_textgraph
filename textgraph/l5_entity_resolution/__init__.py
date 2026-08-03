"""L5 — Entity Resolution & Canonicalization.

Blocking → scoring → non-destructive clustering that links alias entities
("Acme Corp" / "Acme Corporation" / "ACME") to a canonical node via SAME_AS. The
default backend is deterministic and model-free; Splink (Fellegi-Sunter on DuckDB)
is the optional ``[er]`` backend. See ARCHITECTURE.md.
"""

from textgraph.l5_entity_resolution.audit import render_audit
from textgraph.l5_entity_resolution.emit_er import emit_er
from textgraph.l5_entity_resolution.metrics import bcubed, blocking_recall, reduction_ratio
from textgraph.l5_entity_resolution.model import ERecord, ERResult
from textgraph.l5_entity_resolution.resolve import build_records, run_er

__all__ = [
    "ERResult",
    "ERecord",
    "bcubed",
    "blocking_recall",
    "build_records",
    "emit_er",
    "reduction_ratio",
    "render_audit",
    "run_er",
]
