"""Phase-4 DoD: an agent can answer through tool calls alone (no raw file reads).

Simulates an investigator agent working the money-laundering fixture entirely
through the MCP tool surface: discover via search, expand via neighbors, connect via
path, and justify via why. Asserts that every step is bounded and every factual claim
is backed by a re-verifiable byte citation (G3, G6) — the whole point of the layer.
"""

from pathlib import Path

from textgraph.core.content_address import verify_span_hash
from textgraph.l8_retrieval import QueryEngine
from textgraph.mcp import call_tool
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


def test_agent_answers_through_tools_only() -> None:
    result = build(DOCS)
    raw_by_doc = {ir.doc_id: ir.raw for ir in result.results}
    engine = QueryEngine(result.nodes, result.edges)

    def verify(citations: list[dict[str, object]]) -> int:
        checked = 0
        for c in citations:
            raw = raw_by_doc[str(c["doc_id"])]
            assert verify_span_hash(raw, int(c["start"]), int(c["end"]), str(c["hash"]))
            checked += 1
        return checked

    total_citations = 0

    # 1) Discover: search surfaces the transfer network, cited.
    search = call_tool(engine, "search", {"query": "who transferred funds", "k": 5})
    assert search["hits"]
    for hit in search["hits"]:
        total_citations += verify(hit["citations"])

    # 2) Expand: neighbors of a central party are all typed + cited.
    neighbors = call_tool(engine, "neighbors", {"node": "Acme Corp"})
    assert neighbors["neighbors"]
    for edge in neighbors["neighbors"]:
        assert edge["predicate"]
        total_citations += verify(edge["citations"])

    # 3) Connect: an explainable, cited path between two parties.
    path = call_tool(engine, "path", {"source": "Acme Corp", "target": "Gamma Holdings"})
    assert path["paths"]
    for step in path["paths"][0]["steps"]:
        total_citations += verify(step["citations"])

    # 4) Justify: why returns cited claims about the node.
    why = call_tool(engine, "why", {"node": "Acme Corp"})
    assert why["claims"]
    for claim in why["claims"]:
        total_citations += verify(claim["citations"])

    # The agent never read a raw file, yet every answer was byte-verifiable.
    assert total_citations > 0


def test_search_result_is_bounded() -> None:
    result = build(DOCS)
    engine = QueryEngine(result.nodes, result.edges)
    res = call_tool(
        engine, "search", {"query": "acme beta gamma transfer", "k": 20, "max_tokens": 200}
    )
    # Bounded context: the token ceiling caps how much comes back.
    joined = " ".join(h["snippet"] for h in res["hits"])
    assert len(joined) // 4 <= 400  # generous headroom over the 200-token target
