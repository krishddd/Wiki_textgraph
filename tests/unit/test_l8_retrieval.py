"""L8 retrieval: BM25 + QueryEngine typed tools, bounded and cited."""

from pathlib import Path

from textgraph.l8_retrieval import QueryEngine
from textgraph.l8_retrieval.bm25 import BM25Index
from textgraph.l8_retrieval.model import estimate_tokens
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"
CONTRA = Path(__file__).parent.parent / "fixtures" / "corpora" / "contradiction"


def _engine(path: Path = DOCS) -> QueryEngine:
    result = build(path)
    return QueryEngine(result.nodes, result.edges)


def test_bm25_ranks_the_matching_passage_first() -> None:
    idx = BM25Index([("c1", "acme transferred funds to beta"), ("c2", "unrelated weather report")])
    hits = idx.search("funds transferred", k=2)
    assert hits[0][0] == "c1"
    assert idx.search("", k=2) == []


def test_search_returns_cited_bounded_hits() -> None:
    qe = _engine()
    res = qe.search("who transferred funds", k=4)
    assert res.hits
    assert res.routing in ("local", "global")
    for hit in res.hits:
        assert hit.name
    # Every chunk hit is grounded in a re-verifiable citation.
    assert any(h.citations for h in res.hits)


def test_search_is_deterministic() -> None:
    qe = _engine()
    assert qe.search("funds").to_dict() == qe.search("funds").to_dict()


def test_search_no_match_returns_no_hits() -> None:
    # Regression: a query matching nothing lexically and no entity name must not
    # fabricate hits from uniform-PageRank degree centrality.
    qe = _engine()
    assert qe.search("zzzqqq nonsense xyzzy plugh").hits == []


def test_path_k_shortest_finds_the_alternate() -> None:
    # Acme reaches Gamma directly (CONTROLS) and via Beta (TRANSFERRED x2); both
    # loopless paths must be enumerated by the k-shortest search.
    qe = _engine()
    res = qe.path("Acme Corp", "Gamma Holdings", k=3)
    assert len(res.paths) >= 2
    # Shortest (most likely) first.
    assert res.paths[0].likelihood >= res.paths[-1].likelihood


def test_search_respects_token_budget() -> None:
    qe = _engine()
    tight = qe.search("acme corp transfer beta", k=10, max_tokens=1)
    # A tiny budget keeps at least one hit but truncates the rest.
    assert len(tight.hits) >= 1
    assert tight.truncated or len(tight.hits) == 1


def test_neighbors_are_typed_and_cited() -> None:
    qe = _engine()
    res = qe.neighbors("Acme Corp", k=10)
    assert res.neighbors
    for n in res.neighbors:
        assert n.direction in ("in", "out")
        assert n.citations


def test_path_is_maximum_likelihood_and_cited() -> None:
    qe = _engine()
    res = qe.path("Acme Corp", "Gamma Holdings", k=1)
    assert res.paths
    p = res.paths[0]
    assert 0.0 < p.likelihood <= 1.0
    assert p.steps and all(s.citations for s in p.steps)


def test_why_returns_claims_about_the_node() -> None:
    qe = _engine()
    res = qe.why("Acme Corp")
    assert res.claims
    assert all(c.subject == "Acme Corp" or c.object == "Acme Corp" for c in res.claims)


def test_timeline_orders_by_validity() -> None:
    qe = _engine()
    res = qe.timeline("Acme Corp")
    dated = [c.t_valid for c in res.events if c.t_valid]
    assert dated == sorted(dated)


def test_contradictions_pairs_two_claims() -> None:
    qe = _engine(CONTRA)
    res = qe.contradictions()
    assert res.pairs
    pair = res.pairs[0]
    assert pair.claim_a.polarity != pair.claim_b.polarity


def test_communities_and_stats() -> None:
    qe = _engine()
    comms = qe.communities()
    assert comms.communities
    stats = qe.stats()
    assert stats.counts["entities"] > 0
    assert stats.top_entities


def test_estimate_tokens_is_monotonic() -> None:
    assert estimate_tokens("a" * 40) > estimate_tokens("a" * 4)
