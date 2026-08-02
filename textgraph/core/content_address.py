"""Content addressing (G3, G5).

Every document and every cached chunk is identified by the blake3 hash of its
raw bytes. This gives us stable ``doc_id``s (provenance) and a content-addressed
cache key for incremental rebuilds (one changed file -> one changed hash).
"""

from __future__ import annotations

import blake3

DOC_ID_PREFIX = "blake3:"


def blake3_hex(data: bytes) -> str:
    """Return the lowercase hex blake3 digest of ``data``.

    Deterministic and pure: identical bytes always hash identically, which is the
    foundation of G1 (determinism) and G5 (content-addressed incrementality).
    """
    return blake3.blake3(data).hexdigest()


def hash_text(text: str) -> str:
    """Blake3 of ``text``, surrogate-safe.

    Text derived from canonical content may contain lone surrogates (from
    undecodable source bytes decoded with surrogateescape). Encoding with
    ``surrogateescape`` never raises and stays deterministic, so this is the right
    primitive for content-addressing node/edge ids off canonical text (G1).
    """
    return blake3_hex(text.encode("utf-8", errors="surrogateescape"))


def doc_id_for(raw: bytes) -> str:
    """Return the canonical document id for ``raw`` bytes.

    The id is namespaced (``blake3:<hex>``) so that the hash algorithm is part of
    the identifier and can be migrated without ambiguity.
    """
    return f"{DOC_ID_PREFIX}{blake3_hex(raw)}"


def verify_span_hash(raw: bytes, start: int, end: int, expected_hex: str) -> bool:
    """Re-hash the raw byte span ``raw[start:end]`` and compare to ``expected_hex``.

    This is the primitive behind the provenance-integrity test (G3): a stored
    citation is re-verifiable iff re-hashing its exact source bytes still matches.
    """
    if start < 0 or end > len(raw) or start > end:
        return False
    return blake3_hex(raw[start:end]) == expected_hex
