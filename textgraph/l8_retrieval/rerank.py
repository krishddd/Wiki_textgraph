"""Second-stage reranking for hybrid search (L8).

First-stage fusion (BM25 + Personalized PageRank via RRF) casts a wide net; this
stage reorders the survivors. The **builtin** reranker is pure-Python and
deterministic (G1). It reflects what this tool actually is — a *knowledge-graph*
search, where the answer is usually an entity and passages are its supporting
evidence. It sorts each kind by relevance (fusion score + a lexical query-overlap
bonus) and then **interleaves** them (entity, passage, entity, passage, …) so the
graph's answer-entities surface near the top instead of being buried beneath every
lexically-matching chunk — while a genuinely on-point passage still lands at rank 2.
A cross-encoder (``[rerank]`` extra) is the optional higher-quality upgrade,
import-guarded with a clean fallback — the same pattern as the other heavy backends.
"""

from __future__ import annotations

from textgraph.l0_ingest.base import UnsupportedFormat
from textgraph.l8_retrieval.bm25 import tokenize
from textgraph.l8_retrieval.model import SearchHit

# Weight of the lexical overlap bonus relative to the (small) RRF base score.
_OVERLAP_WEIGHT = 0.02


def _relevance(query_tokens: set[str], hit: SearchHit) -> float:
    text = hit.name if hit.kind == "entity" else (hit.snippet or hit.name)
    overlap = len(query_tokens & set(tokenize(text)))
    return hit.score + _OVERLAP_WEIGHT * overlap


def rerank(query: str, hits: list[SearchHit], *, backend: str = "builtin") -> list[SearchHit]:
    """Reorder ``hits`` by relevance to ``query`` (deterministic for the default backend)."""
    if backend == "cross-encoder":
        try:
            return _cross_encoder_rerank(query, hits)
        except UnsupportedFormat:
            pass  # fall back to the deterministic builtin
    qt = set(tokenize(query))

    def by_rel(kind: str) -> list[SearchHit]:
        return sorted(
            (h for h in hits if h.kind == kind),
            key=lambda h: (-_relevance(qt, h), h.node_id),
        )

    entities, chunks = by_rel("entity"), by_rel("chunk")
    # Interleave entity, passage, entity, passage … — the answer node and its evidence,
    # alternating — so neither kind monopolises the top of the list.
    merged: list[SearchHit] = []
    for ent, ch in zip(entities, chunks, strict=False):
        merged.append(ent)
        merged.append(ch)
    tail = entities[len(chunks) :] if len(entities) > len(chunks) else chunks[len(entities) :]
    merged.extend(tail)
    return merged


def _cross_encoder_rerank(query: str, hits: list[SearchHit]) -> list[SearchHit]:
    """Reorder with a cross-encoder relevance model (behind the ``[rerank]`` extra)."""
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise UnsupportedFormat(
            "cross-encoder reranking requires the [rerank] extra (sentence-transformers)"
        ) from exc
    model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")  # pragma: no cover
    pairs = [(query, h.snippet or h.name) for h in hits]  # pragma: no cover
    scores = model.predict(pairs)  # pragma: no cover
    order = sorted(  # pragma: no cover
        range(len(hits)), key=lambda i: (-float(scores[i]), hits[i].node_id)
    )
    return [hits[i] for i in order]  # pragma: no cover
