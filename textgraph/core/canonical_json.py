"""Canonical JSON serialization (G1).

Byte-identical output for identical logical content is the backbone of the
determinism guarantee. We enforce:
  * sorted object keys,
  * compact separators (no incidental whitespace),
  * UTF-8, non-ASCII preserved (``ensure_ascii=False``) so hashes are stable across
    locales,
  * a single trailing newline (POSIX-friendly, diff-friendly).

Note on arrays: JSON array order is *semantic* and is never reordered here. Layers
that emit collections are responsible for sorting them by a stable key *before*
serialization (e.g. edges sorted by ``(subject, predicate, object, source_span)``).
"""

from __future__ import annotations

import json
from typing import Any


def canonical_dumps(obj: Any) -> str:
    """Serialize ``obj`` to a canonical JSON string (sorted keys, compact, +\\n)."""
    return (
        json.dumps(
            obj,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    )


def canonical_dump_bytes(obj: Any) -> bytes:
    """Serialize ``obj`` to canonical JSON UTF-8 bytes (for hashing / writing)."""
    return canonical_dumps(obj).encode("utf-8")
