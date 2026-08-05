"""Page-level late-interaction retrieval (Phase 8).

Treats each **document as a page** — the retrievable unit ColPali scores — and ranks
pages against a query with :func:`~textgraph.l8_retrieval.vision.maxsim.maxsim` over
multi-vector embeddings. This is the vision-native alternative to BM25 chunk retrieval;
in the default build the "page" is the document's extracted text (deterministic,
CI-safe), and the ``[vision]`` backend swaps in real rendered-page-image patch vectors
without changing this code. Results are bounded and cited (G3/G7), and each page still
seeds Personalized PageRank through the document's existing entity mentions.
"""

from __future__ import annotations

from dataclasses import dataclass

from textgraph.l8_retrieval.model import Citation, SearchHit
from textgraph.l8_retrieval.vision.embed import Embedder, HashEmbedder
from textgraph.l8_retrieval.vision.maxsim import MultiVector, maxsim


@dataclass(frozen=True)
class VisionPage:
    page_id: str
    doc_id: str
    name: str
    text: str
    citation: Citation | None = None


class VisionRetriever:
    """MaxSim page retrieval over a fixed set of pages (embeddings computed once)."""

    def __init__(self, pages: list[VisionPage], embedder: Embedder | None = None) -> None:
        self._embedder = embedder or HashEmbedder()
        self._pages = sorted(pages, key=lambda p: p.page_id)
        self._embeddings: dict[str, MultiVector] = {
            p.page_id: self._embedder.embed(p.text) for p in self._pages
        }

    def search(self, query: str, *, k: int = 5) -> list[SearchHit]:
        """Top-``k`` pages by MaxSim, as cited :class:`SearchHit`s (score-desc).

        Ranking only; the caller applies the shared token budget (G7) so the vision
        channel reports truncation exactly like the other L8 tools.
        """
        q = self._embedder.embed(query)
        scored = [(p, maxsim(q, self._embeddings[p.page_id])) for p in self._pages]
        ranked = sorted((ps for ps in scored if ps[1] > 0), key=lambda ps: (-ps[1], ps[0].page_id))
        return [
            SearchHit(
                node_id=p.page_id,
                kind="page",
                name=p.name,
                score=score,
                snippet=p.text[:280],
                citations=[p.citation] if p.citation else [],
            )
            for p, score in ranked[:k]
        ]
