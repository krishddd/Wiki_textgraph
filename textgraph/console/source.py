"""Serve the source bytes behind a citation, for the Ask dock's click-through.

A citation is `[doc:start-end]` — a re-verifiable byte range (G3). The dock used to render
that as inert text; this module turns it into a window into the actual document: the exact
cited span, plus a little surrounding context, with the span **re-hashed against the source
bytes on read** so the panel proves the citation rather than just quoting it.

Everything here is read-only and defensive:

* **Content-addressed integrity.** The document is located by its content id, and the raw
  file on disk is confirmed to still hash to that id before a single byte is returned — a
  since-edited file is reported as a mismatch, never silently shown.
* **Graceful degradation.** The console can run from a bare ``graph.json`` or a ``.duckdb``
  snapshot with **no corpus directory**. In that case there is nothing to read, so the
  endpoint returns ``available: false`` and the UI keeps the old text-only citation — it
  never errors.
* **Traversal-safe.** The document's stored relative path is resolved under the corpus root
  and rejected if it escapes (same guard as document removal).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textgraph.core.content_address import doc_id_for, verify_span_hash

# How much text to show on each side of the cited span, in bytes of the source.
_CONTEXT = 240
_DOC_PREFIX = "doc:"


def _document_path(engine: Any, doc_id: str) -> str | None:
    """Return the stored relative path for a citation ``doc_id`` (``blake3:…``), if known."""
    node = engine._node.get(_DOC_PREFIX + doc_id) if hasattr(engine, "_node") else None
    if node is None:
        return None
    path = node.properties.get("path") or node.properties.get("name")
    return str(path) if path else None


def read_span(
    engine: Any,
    source: str | None,
    doc_id: str,
    start: int,
    end: int,
    *,
    expected_hash: str | None = None,
) -> dict[str, Any]:
    """Read the cited byte range from its source document, verified.

    Returns a payload the UI can render directly::

        {available, doc_id, name, start, end, verified,
         before, span, after}                         # on success
        {available: False, reason: "..."}             # when there is no readable source

    ``available`` is False (not an error) whenever the console has no corpus dir, the
    document isn't on disk, or the file no longer matches its content id — so the caller can
    fall back to the plain-text citation.
    """
    name = _document_path(engine, doc_id) or doc_id
    if not source or not Path(source).is_dir():
        return {"available": False, "reason": "no-corpus", "name": name}

    rel = _document_path(engine, doc_id)
    if rel is None:
        return {"available": False, "reason": "unknown-document", "name": name}

    root = Path(source).resolve()
    try:
        target = (root / rel).resolve()
        target.relative_to(root)  # traversal guard: must stay under the corpus root
    except (ValueError, OSError):
        return {"available": False, "reason": "path-escape", "name": name}
    if not target.is_file():
        return {"available": False, "reason": "not-on-disk", "name": name}

    raw = target.read_bytes()
    # The file must still be the exact document the citation points at. doc_id is the
    # content hash of the raw bytes, so a re-hash mismatch means the file was edited.
    if doc_id_for(raw) != doc_id:
        return {"available": False, "reason": "source-changed", "name": name}

    n = len(raw)
    s = max(0, min(start, n))
    e = max(s, min(end, n))
    verified = verify_span_hash(raw, s, e, expected_hash) if expected_hash else None

    def _dec(a: int, b: int) -> str:
        return raw[a:b].decode("utf-8", errors="replace")

    return {
        "available": True,
        "doc_id": doc_id,
        "name": name,
        "start": s,
        "end": e,
        "verified": verified,
        "before": _dec(max(0, s - _CONTEXT), s),
        "span": _dec(s, e),
        "after": _dec(e, min(n, e + _CONTEXT)),
    }
