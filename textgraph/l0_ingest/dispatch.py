"""L0 dispatch: pick an ingestor by file extension, fall back to plain text.

Importing this module registers every built-in ingestor. Rich-document formats
(PDF/DOCX/PPTX via Docling) and tree-sitter grammars register here too once the
``[ingest]`` extra is installed; without it, those extensions fall back to plain
text rather than crashing (G2: default install stays functional).
"""

from __future__ import annotations

from pathlib import Path

from textgraph.core.layout import IngestResult

# Registering imports (side effects populate the registry). Order is deterministic.
from textgraph.l0_ingest import (  # noqa: F401
    logs,
    markdown,
    plaintext,
    richdocs,
    structured,
    transcript,
)
from textgraph.l0_ingest.base import get_ingestor
from textgraph.l0_ingest.plaintext import ingest_plaintext


def ingest_path(path: str | Path) -> IngestResult:
    """Ingest a single file, choosing an ingestor by extension."""
    path = Path(path)
    raw = path.read_bytes()
    return ingest_bytes(raw, source_name=path.name, extension=path.suffix)


def ingest_bytes(raw: bytes, *, source_name: str, extension: str) -> IngestResult:
    """Ingest raw bytes with an explicit extension (used by tests and streams)."""
    ingestor = get_ingestor(extension) or ingest_plaintext
    return ingestor(raw, source_name)
