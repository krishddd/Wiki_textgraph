"""Sprint 2.5 tests: LangChain / LlamaIndex adapters preserve byte-span citations (G3)."""

from pathlib import Path

import pytest
from textgraph.integrations import (
    make_langchain_retriever,
    make_llamaindex_retriever,
    search_to_documents,
    search_to_nodes,
)
from textgraph.l0_ingest.base import UnsupportedFormat
from textgraph.l8_retrieval import QueryEngine
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


def _engine() -> QueryEngine:
    r = build(DOCS)
    return QueryEngine(r.nodes, r.edges)


def test_langchain_documents_carry_citations() -> None:
    docs = search_to_documents(_engine(), "who transferred funds", k=5)
    assert docs
    for d in docs:
        assert "page_content" in d and "metadata" in d
        md = d["metadata"]
        assert {"node_id", "kind", "citations", "source"} <= md.keys()
    # At least one hit is a cited chunk — provenance survives into metadata (G3).
    assert any(d["metadata"]["citations"] for d in docs)


def test_llamaindex_nodes_carry_citations_and_score() -> None:
    nodes = search_to_nodes(_engine(), "who transferred funds", k=5)
    assert nodes
    for n in nodes:
        assert "text" in n and "score" in n and "citations" in n["metadata"]
    assert any(n["metadata"]["citations"] for n in nodes)


def test_converters_are_deterministic() -> None:
    eng = _engine()
    assert search_to_documents(eng, "acme", k=5) == search_to_documents(eng, "acme", k=5)


def test_retriever_factories_require_the_extra() -> None:
    # LangChain / LlamaIndex aren't installed in the lean CI: the factories must raise a
    # clear UnsupportedFormat rather than a bare ImportError.
    eng = _engine()
    try:
        import langchain_core  # noqa: F401
    except ImportError:
        with pytest.raises(UnsupportedFormat, match="langchain"):
            make_langchain_retriever(eng)
    try:
        import llama_index  # noqa: F401
    except ImportError:
        with pytest.raises(UnsupportedFormat, match="llamaindex"):
            make_llamaindex_retriever(eng)
