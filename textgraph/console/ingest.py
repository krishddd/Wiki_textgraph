"""File ingestion for the console 'Ask' chat (Phase C) — the one write path.

Dropping a file into the chat adds it to the live graph. This module is the pure,
socket-free core: a minimal ``multipart/form-data`` parser (stdlib only — ``cgi`` was
removed in Python 3.13), strict filename sanitisation, an extension allowlist, and an
incremental rebuild that re-extracts only the new document (``build(root,
cache_dir=…)`` is byte-identical to a full build, so the resulting graph is exactly what a
clean rebuild of the enlarged corpus would produce).

Ingestion is a *mutation*, so the server only wires it when ``--allow-ingest`` is passed,
and everything here writes strictly inside the corpus directory (basename-only names, no
traversal). Determinism is preserved run-to-run for a given corpus; adding a file
legitimately changes the corpus, and hence the graph.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from textgraph.pipeline import build
from textgraph.store.base import Edge, Node

# Text formats the deterministic default path can ingest with no extra installed. (PDF and
# other rich formats need the [ingest] extra; we reject them here with a clear message
# rather than let the rebuild raise.)
_ALLOWED_EXT = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".text",
        ".html",
        ".htm",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".log",
        ".csv",
        ".rst",
    }
)
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file — a console upload, not a data pipeline


@dataclass
class IngestResult:
    """Outcome of an ingest: the rebuilt graph plus what changed."""

    ok: bool
    written: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


def sanitize_name(name: str) -> str:
    """Reduce an uploaded filename to a safe basename inside the corpus dir (no traversal)."""
    base = name.replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")
    return base[:120] or "upload.txt"


def allowed(name: str) -> bool:
    return Path(name).suffix.lower() in _ALLOWED_EXT


def parse_multipart(content_type: str, body: bytes) -> list[tuple[str, bytes]]:
    """Extract ``(filename, bytes)`` file parts from a ``multipart/form-data`` body.

    Minimal but correct for browser uploads: splits on the declared boundary and strips
    only the framing CRLFs, so a file's own leading/trailing newlines are preserved.
    """
    m = re.search(r"boundary=([^;]+)", content_type)
    if not m:
        return []
    delim = b"--" + m.group(1).strip().strip('"').encode()
    files: list[tuple[str, bytes]] = []
    for part in body.split(delim):
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        if not part or part == b"--" or b"\r\n\r\n" not in part:
            continue
        headers_raw, data = part.split(b"\r\n\r\n", 1)
        fm = re.search(r'filename="([^"]*)"', headers_raw.decode("utf-8", "replace"))
        if fm and fm.group(1):
            files.append((fm.group(1), data))
    return files


def ingest_files(
    source: str | Path, uploads: list[tuple[str, bytes]], *, cache_dir: str | Path | None = None
) -> IngestResult:
    """Write allowed uploads into the corpus dir and incrementally rebuild the graph.

    Returns the rebuilt ``(nodes, edges)`` and the accepted/rejected filenames. Rejects
    (unsupported extension, oversize, or a target directory) never touch disk.
    """
    root = Path(source)
    if not root.is_dir():
        return IngestResult(ok=False)
    written: list[str] = []
    rejected: list[str] = []
    for raw_name, data in uploads:
        safe = sanitize_name(raw_name)
        if not allowed(safe) or len(data) > _MAX_BYTES:
            rejected.append(raw_name)
            continue
        target = (root / safe).resolve()
        if root.resolve() not in target.parents:  # defence in depth against traversal
            rejected.append(raw_name)
            continue
        target.write_bytes(data)
        written.append(safe)
    if not written:
        return IngestResult(ok=False, rejected=rejected)
    result = build(root, cache_dir=cache_dir)
    return IngestResult(
        ok=True, written=written, rejected=rejected, nodes=result.nodes, edges=result.edges
    )


def list_documents(source: str | Path) -> list[dict[str, object]]:
    """List the ingestible files in the corpus directory (name + size), sorted by name.

    Empty when ``source`` is not a directory (a ``graph.json`` / ``.duckdb`` snapshot has no
    editable corpus behind it).
    """
    from textgraph.pipeline import _iter_corpus_files

    root = Path(source)
    if not root.is_dir():
        return []
    return [
        {"name": str(p.relative_to(root)).replace("\\", "/"), "bytes": p.stat().st_size}
        for p in _iter_corpus_files(root)
    ]


def remove_document(
    source: str | Path, name: str, *, cache_dir: str | Path | None = None
) -> IngestResult:
    """Delete one document from the corpus dir (traversal-safe) and rebuild the graph.

    The inverse of :func:`ingest_files`; only the named file is removed, then the graph is
    rebuilt from whatever remains. Returns ``ok=False`` if the path escapes the corpus or the
    file is absent. Deleting an empty corpus rebuilds to an empty graph (still ``ok``).
    """
    root = Path(source)
    if not root.is_dir():
        return IngestResult(ok=False)
    target = (root / name).resolve()
    if root.resolve() not in target.parents or not target.is_file():
        return IngestResult(ok=False)
    target.unlink()
    result = build(root, cache_dir=cache_dir)
    return IngestResult(ok=True, written=[name], nodes=result.nodes, edges=result.edges)
