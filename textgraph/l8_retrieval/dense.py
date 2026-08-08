"""Dense-embedding retrieval — the semantic signal fused into hybrid search.

BM25 is lexical: it misses paraphrase ("high-risk AI systems" vs "systems posing
significant risk"). A dense embedder adds a *semantic* signal, and TextGraph fuses it
into the existing BM25 + Personalized-PageRank RRF blend rather than replacing anything —
so lexical precision, graph association, and semantic recall all vote.

Three backends behind one interface, following the project's upgrade-or-fall-back rule:

* **``openai`` (dependency-free).** Speaks the OpenAI-compatible ``/embeddings`` API with
  stdlib ``urllib`` — so it works against a **local Ollama** (``nomic-embed-text``), a
  local vLLM, or OpenAI, by pointing ``embed_base_url`` at it. The API key (if any) is read
  from the environment only, never stored (secret hygiene, like the L4 chat client).
* **``st`` (``[embed]`` extra).** A local ``sentence-transformers`` model — fully offline,
  no server. Import-guarded: absent extra falls back rather than failing.
* **``hash`` (deterministic, CI-safe).** A pure-stdlib SHAKE-256 embedder with no
  semantics — it exists so the *fusion pipeline* can be tested reproducibly with no model.

Embeddings are **query-time only** — they never enter ``graph.json`` — so the deterministic
build guarantee (G1) is untouched whether or not an embedder is configured.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from textgraph.core.config import Config
from textgraph.l8_retrieval.bm25 import tokenize

_API_KEY_ENV = ("TEXTGRAPH_EMBED_API_KEY", "TEXTGRAPH_LLM_API_KEY", "API_KEY", "OPENAI_API_KEY")


class EmbedError(RuntimeError):
    """Raised when a remote embedding endpoint is unreachable or returns an error."""


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors (0.0 if either is a zero vector)."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na > 0 and nb > 0 else 0.0


class TextEmbedder(Protocol):
    """Anything that turns text (a chunk or a query) into a single dense vector."""

    dim: int

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class HashTextEmbedder:
    """Deterministic, model-free embedder (CI-safe). Bag-of-token-hashes, L2-normalised.

    Carries no real semantics, but it lets the dense-fusion path be exercised and tested
    reproducibly with zero model or network (G1) — the same role ``HashEmbedder`` plays for
    vision retrieval.
    """

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in tokenize(text):
            h = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            sign = 1.0 if h[4] & 1 else -1.0
            v[idx] += sign
        norm = math.sqrt(sum(x * x for x in v))
        return [x / norm for x in v] if norm > 0 else v

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class OpenAIEmbedder:
    """OpenAI-compatible ``/embeddings`` client (stdlib urllib). Works with Ollama/vLLM/OpenAI."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        dim: int = 0,
        timeout: float = 120.0,
        batch_size: int = 32,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = dim  # 0 until the first response tells us the true dimension
        self.timeout = timeout
        self.batch_size = max(1, batch_size)
        self._api_key = next((os.environ[n] for n in _API_KEY_ENV if os.environ.get(n)), "")

    def _post(self, texts: list[str]) -> list[list[float]]:
        payload = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = urllib.request.Request(
            f"{self.base_url}/embeddings", data=payload, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise EmbedError(f"embedding endpoint failed: {exc}") from exc
        return [row["embedding"] for row in sorted(body["data"], key=lambda r: r["index"])]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # Sub-batch so a large corpus doesn't exceed the per-request timeout on a small
        # local embedder (Ollama embeds sequentially).
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            vectors.extend(self._post(texts[i : i + self.batch_size]))
        if vectors and not self.dim:
            self.dim = len(vectors[0])
        return vectors


class CachedEmbedder:
    """Wrap any embedder with a persistent disk cache — only cache-*misses* hit the model.

    Embedding a large corpus once is expensive (a local model runs sequentially); the cache
    makes every later run — repeated queries, console sessions, re-ingest — effectively free.
    Keyed by ``sha256(namespace + text)`` so a model/dimension change is a clean cache miss.
    """

    def __init__(self, inner: TextEmbedder, cache_dir: str | Path, namespace: str) -> None:
        self.inner = inner
        self.dim = inner.dim
        self.namespace = namespace
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", namespace)
        self._path = Path(cache_dir) / f"embed-{safe}.json"
        self._cache: dict[str, list[float]] = {}
        if self._path.exists():
            try:
                self._cache = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.namespace}\x00{text}".encode()).hexdigest()[:24]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        keys = [self._key(t) for t in texts]
        misses = [t for t, k in zip(texts, keys, strict=False) if k not in self._cache]
        if misses:
            fresh = self.inner.embed_batch(misses)
            for t, vec in zip(misses, fresh, strict=False):
                self._cache[self._key(t)] = vec
            self.dim = self.inner.dim
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._cache), encoding="utf-8")
        if not self.dim and self._cache:
            self.dim = len(next(iter(self._cache.values())))
        return [self._cache[k] for k in keys]


def resolve_text_embedder(
    config: Config, *, cache_dir: str | Path | None = None
) -> TextEmbedder | None:
    """Return the configured text embedder, or ``None`` when dense retrieval is off.

    ``embed_backend`` selects the backend; ``st`` falls back to ``None`` (dense disabled)
    if ``sentence-transformers`` isn't installed, rather than failing the query. When
    ``cache_dir`` is given the embedder is wrapped in a persistent :class:`CachedEmbedder`.
    """
    backend = config.embed_backend
    if not backend:
        return None
    inner: TextEmbedder | None
    if backend == "hash":
        inner = HashTextEmbedder(dim=config.embed_dim or 256)
    elif backend == "openai":
        inner = OpenAIEmbedder(config.embed_base_url, config.embed_model, dim=config.embed_dim)
    elif backend == "st":
        try:
            inner = _st_embedder(config)
        except ImportError:
            return None
    else:
        return None
    if cache_dir is None:
        return inner
    namespace = f"{backend}:{config.embed_model}:{config.embed_dim}"
    return CachedEmbedder(inner, cache_dir, namespace)


def _st_embedder(config: Config) -> TextEmbedder:  # pragma: no cover - needs [embed]
    """Local sentence-transformers embedder (behind the ``[embed]`` extra)."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(config.embed_model or "all-MiniLM-L6-v2")

    class _ST:
        dim = int(model.get_sentence_embedding_dimension())

        def embed_batch(self, texts: list[str]) -> list[list[float]]:
            return [v.tolist() for v in model.encode(texts, normalize_embeddings=True)]

    return _ST()
