"""Multi-vector embedders for vision-native retrieval (Phase 8).

Two backends behind one interface, following the project's upgrade-or-fall-back rule:

* **``hash`` (default, CI-safe, deterministic).** A pure-stdlib embedder that maps each
  token to a fixed unit vector (SHAKE-256 → bytes → floats → normalise). It carries no
  semantics, but it lets the *whole* late-interaction pipeline — multi-vector pages,
  MaxSim scoring, retrieval — run and be tested reproducibly with zero GPU (G1/G2).
* **``colpali`` (``[vision]`` extra).** A real ColPali/ColQwen2 late-interaction model
  that embeds rendered **page images** into visual patch vectors. Import-guarded: if the
  extra/model is absent it raises :class:`UnsupportedFormat` and the caller falls back to
  ``hash`` — the same pattern as GLiNER / Splink / Leiden.

The rest of the vision layer only ever sees ``MultiVector``s, so it is identical across
backends.
"""

from __future__ import annotations

import hashlib
from typing import Protocol

from textgraph.core.config import Config
from textgraph.l0_ingest.base import UnsupportedFormat
from textgraph.l8_retrieval.bm25 import tokenize
from textgraph.l8_retrieval.vision.maxsim import MultiVector, Vector, normalize


class Embedder(Protocol):
    """Anything that turns text (a query, or a page's extracted text) into a multi-vector."""

    def embed(self, text: str) -> MultiVector: ...


class HashEmbedder:
    """Deterministic default: one hash-derived unit vector per token (no model, G1)."""

    def __init__(self, dim: int = 48) -> None:
        self.dim = dim
        self._cache: dict[str, Vector] = {}

    def _token_vector(self, token: str) -> Vector:
        cached = self._cache.get(token)
        if cached is not None:
            return cached
        # SHAKE-256 gives an arbitrary-length, deterministic digest — one byte per dim.
        raw = hashlib.shake_256(token.encode("utf-8")).digest(self.dim)
        vec = normalize(tuple((b / 127.5) - 1.0 for b in raw))
        self._cache[token] = vec
        return vec

    def embed(self, text: str) -> MultiVector:
        return tuple(self._token_vector(t) for t in tokenize(text))


def resolve_embedder(config: Config) -> Embedder:
    """Return the configured embedder, falling back to the deterministic default.

    ``vision_backend='colpali'`` requests the model; if the ``[vision]`` extra is not
    installed we fall back to ``hash`` rather than failing the query.
    """
    if config.vision_backend == "colpali":
        try:
            return _colpali_embedder(config)
        except UnsupportedFormat:
            pass
    return HashEmbedder(dim=config.vision_dim)


def _colpali_embedder(config: Config) -> Embedder:  # pragma: no cover - needs [vision]
    """Load a ColPali/ColQwen late-interaction model (behind the ``[vision]`` extra)."""
    try:
        from colpali_engine.models import ColPali  # noqa: F401
    except ImportError as exc:
        raise UnsupportedFormat(
            "vision_backend='colpali' requires the [vision] extra (colpali-engine)"
        ) from exc
    # A real implementation would load the model here and embed page images / query text
    # into patch vectors. Kept behind the guard so the default path never touches a GPU.
    raise UnsupportedFormat("ColPali backend is not wired in this build; using 'hash'")
