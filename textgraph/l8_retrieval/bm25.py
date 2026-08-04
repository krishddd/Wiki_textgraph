"""Pure-Python BM25 over chunk texts (L8 lexical retrieval, CI-safe default).

No numpy, no external index — a dict-of-postings BM25 with the standard Okapi
weighting (``k1=1.5``, ``b=0.75``). Deterministic: identical corpus + query yield an
identical, stably-tied ranking (G1). This is the lexical half of hybrid search; the
graph half (Personalized PageRank) lives in the engine, and the two are fused with
Reciprocal Rank Fusion. A cross-encoder reranker is the optional ``[ie]``/reranker
upgrade, layered on top without changing this contract.
"""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")
_K1 = 1.5
_B = 0.75


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, length >= 2 (deterministic)."""
    return [t for t in _TOKEN.findall(text.lower()) if len(t) >= 2]


class BM25Index:
    """A tiny inverted-index BM25 ranker over ``(doc_id, text)`` passages."""

    def __init__(self, documents: list[tuple[str, str]]) -> None:
        # documents: list of (chunk_id, text), kept in sorted id order for determinism.
        self._docs = sorted(documents, key=lambda d: d[0])
        self._tokens: dict[str, list[str]] = {cid: tokenize(text) for cid, text in self._docs}
        self._len: dict[str, int] = {cid: len(toks) for cid, toks in self._tokens.items()}
        self._tf: dict[str, Counter[str]] = {
            cid: Counter(toks) for cid, toks in self._tokens.items()
        }
        n = len(self._docs)
        self._avgdl = (sum(self._len.values()) / n) if n else 0.0
        df: Counter[str] = Counter()
        for toks in self._tokens.values():
            for term in set(toks):
                df[term] += 1
        # Okapi idf with the standard +1 floor so it never goes negative.
        self._idf: dict[str, float] = {
            term: math.log(1 + (n - d + 0.5) / (d + 0.5)) for term, d in df.items()
        }

    def score(self, query_tokens: list[str], chunk_id: str) -> float:
        tf = self._tf.get(chunk_id)
        if not tf:
            return 0.0
        dl = self._len[chunk_id]
        denom_norm = _K1 * (1 - _B + _B * dl / self._avgdl) if self._avgdl else _K1
        total = 0.0
        for term in query_tokens:
            f = tf.get(term, 0)
            if f == 0:
                continue
            total += self._idf.get(term, 0.0) * (f * (_K1 + 1)) / (f + denom_norm)
        return total

    def search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        """Top-``k`` ``(chunk_id, score)`` for ``query``, score-desc then id-asc."""
        q = tokenize(query)
        if not q:
            return []
        scored = [(cid, self.score(q, cid)) for cid, _ in self._docs]
        ranked = sorted((p for p in scored if p[1] > 0), key=lambda p: (-p[1], p[0]))
        return ranked[:k]
