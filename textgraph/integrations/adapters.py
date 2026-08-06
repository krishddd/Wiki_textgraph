"""LangChain / LlamaIndex retriever adapters over the L8 QueryEngine (Sprint 2.5).

The pure converters (:func:`search_to_documents`, :func:`search_to_nodes`) turn a
:class:`~textgraph.l8_retrieval.model.SearchResult` into framework-shaped payloads that
**keep every byte-span citation in metadata** — so a LangChain `Document` or a LlamaIndex
`TextNode` produced here can still be re-verified against source bytes (G3). They are
deterministic and dependency-free, so they're unit-tested in the lean CI.

The framework retriever *classes* (:func:`make_langchain_retriever`,
:func:`make_llamaindex_retriever`) subclass each framework's ``BaseRetriever`` and are
import-guarded behind the ``[langchain]`` / ``[llamaindex]`` extras — instantiating them
without the framework installed raises ``UnsupportedFormat`` with a clear message. They're
thin wrappers over the pure converters, so the conversion logic (the part that matters for
provenance) is fully tested even though the framework glue is not exercised in CI.

**G3 check:** neither framework forces dropping citations — both `Document.metadata` and
`TextNode.metadata` are free-form dicts — so the adapters preserve provenance. If a future
framework required opaque, metadata-less chunks, that would violate G3 and we would *not*
ship the adapter; that is not the case for LangChain or LlamaIndex today.
"""

from __future__ import annotations

from typing import Any

from textgraph.l0_ingest.base import UnsupportedFormat
from textgraph.l8_retrieval.engine import QueryEngine
from textgraph.l8_retrieval.model import SearchHit, SearchResult


def _citations(hit: SearchHit) -> list[dict[str, Any]]:
    return [c.to_dict() for c in hit.citations]


def _content(hit: SearchHit) -> str:
    return hit.snippet or hit.name


def _metadata(hit: SearchHit, query: str, routing: str) -> dict[str, Any]:
    cites = _citations(hit)
    return {
        "node_id": hit.node_id,
        "kind": hit.kind,
        "name": hit.name,
        "score": round(hit.score, 6),
        "routing": routing,
        "query": query,
        # The provenance that makes this G3-safe — a re-verifiable byte range per source.
        "citations": cites,
        "source": cites[0]["doc_id"] if cites else "",
    }


def search_to_documents(engine: QueryEngine, query: str, *, k: int = 5) -> list[dict[str, Any]]:
    """Run search and return LangChain-``Document``-shaped dicts (``page_content`` + ``metadata``).

    Pure/deterministic and framework-free, so it's testable without LangChain installed; the
    real retriever class wraps these into ``langchain_core.documents.Document`` objects.
    """
    result: SearchResult = engine.search(query, k=k)
    return [
        {"page_content": _content(h), "metadata": _metadata(h, query, result.routing)}
        for h in result.hits
    ]


def search_to_nodes(engine: QueryEngine, query: str, *, k: int = 5) -> list[dict[str, Any]]:
    """Run search; return LlamaIndex ``TextNode``-shaped dicts (``text``/``metadata``/``score``)."""
    result: SearchResult = engine.search(query, k=k)
    return [
        {
            "text": _content(h),
            "score": round(h.score, 6),
            "metadata": _metadata(h, query, result.routing),
        }
        for h in result.hits
    ]


def make_langchain_retriever(engine: QueryEngine, *, k: int = 5) -> Any:
    """A ``langchain_core.retrievers.BaseRetriever`` over the graph (needs ``[langchain]``)."""
    try:  # pragma: no cover - needs the [langchain] extra
        from langchain_core.documents import Document
        from langchain_core.retrievers import BaseRetriever
    except ImportError as exc:
        raise UnsupportedFormat(
            "LangChain adapter needs an extra: install 'textgraph[langchain]'"
        ) from exc

    class TextGraphRetriever(BaseRetriever):  # type: ignore[misc]  # pragma: no cover
        def _get_relevant_documents(self, query: str, *, run_manager: Any = None) -> list[Any]:
            return [
                Document(page_content=d["page_content"], metadata=d["metadata"])
                for d in search_to_documents(engine, query, k=k)
            ]

    return TextGraphRetriever()


def make_llamaindex_retriever(engine: QueryEngine, *, k: int = 5) -> Any:
    """A ``llama_index.core.retrievers.BaseRetriever`` over the graph (needs ``[llamaindex]``)."""
    try:  # pragma: no cover - needs the [llamaindex] extra
        from llama_index.core.retrievers import BaseRetriever
        from llama_index.core.schema import NodeWithScore, TextNode
    except ImportError as exc:
        raise UnsupportedFormat(
            "LlamaIndex adapter needs an extra: install 'textgraph[llamaindex]'"
        ) from exc

    class TextGraphLlamaRetriever(BaseRetriever):  # type: ignore[misc]  # pragma: no cover
        def _retrieve(self, query_bundle: Any) -> list[Any]:
            q = getattr(query_bundle, "query_str", str(query_bundle))
            return [
                NodeWithScore(
                    node=TextNode(text=n["text"], metadata=n["metadata"]), score=n["score"]
                )
                for n in search_to_nodes(engine, q, k=k)
            ]

    return TextGraphLlamaRetriever()
