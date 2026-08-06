"""Framework adapters — consume the TextGraph graph from LangChain / LlamaIndex (G3-safe).

TextGraph's edge over generic GraphRAG is byte-level provenance: every retrieved passage
carries a re-verifiable ``[doc:start-end]`` citation. These adapters expose the graph to the
LangChain and LlamaIndex ecosystems **without dropping that citation** — both frameworks
attach arbitrary ``metadata`` to their document/node types, so the citations ride along in
metadata and G3 is preserved. See :mod:`textgraph.integrations.adapters`.
"""

from textgraph.integrations.adapters import (
    make_langchain_retriever,
    make_llamaindex_retriever,
    search_to_documents,
    search_to_nodes,
)

__all__ = [
    "make_langchain_retriever",
    "make_llamaindex_retriever",
    "search_to_documents",
    "search_to_nodes",
]
