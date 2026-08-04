"""L7 analytics: deterministic algorithms + graph enrichment."""

from pathlib import Path

from textgraph.l7_analytics import compute_analytics
from textgraph.l7_analytics.algorithms import (
    betweenness,
    build_adjacency,
    connected_components,
    is_bridge,
    pagerank,
)
from textgraph.l7_analytics.communities import label_propagation
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"
CONTRA = Path(__file__).parent.parent / "fixtures" / "corpora" / "contradiction"


def _triangle() -> tuple[list[str], dict[str, list[tuple[str, float]]]]:
    nodes = ["a", "b", "c", "d"]
    # triangle a-b-c plus a pendant d hanging off a (so a-d is a bridge).
    edges = [("a", "b", 1.0), ("b", "c", 1.0), ("c", "a", 1.0), ("a", "d", 1.0)]
    return nodes, build_adjacency(nodes, edges)


def test_pagerank_sums_to_one_and_ranks_hub() -> None:
    nodes, adj = _triangle()
    pr = pagerank(nodes, adj)
    assert abs(sum(pr.values()) - 1.0) < 1e-6
    # 'a' touches the triangle and the pendant, so it is the most central.
    assert max(pr, key=lambda k: pr[k]) == "a"


def test_betweenness_flags_the_cut_vertex() -> None:
    nodes, adj = _triangle()
    bc = betweenness(nodes, adj)
    assert bc["a"] == max(bc.values())


def test_is_bridge_and_components() -> None:
    nodes, adj = _triangle()
    assert is_bridge("a", "d", adj) is True
    assert is_bridge("a", "b", adj) is False
    assert connected_components(nodes, adj) == [["a", "b", "c", "d"]]


def test_label_propagation_is_deterministic() -> None:
    nodes, adj = _triangle()
    assert label_propagation(nodes, adj) == label_propagation(nodes, adj)


def test_compute_analytics_is_deterministic_on_real_graph() -> None:
    result = build(DOCS)
    a = compute_analytics(result.nodes, result.edges)
    b = compute_analytics(result.nodes, result.edges)
    assert a.pagerank == b.pagerank
    assert a.community_of == b.community_of
    assert a.god_nodes == b.god_nodes


def test_enrichment_writes_centrality_onto_entities() -> None:
    result = build(DOCS)
    entities = [n for n in result.nodes if "Entity" in n.labels and "Canonical" not in n.labels]
    assert entities
    for n in entities:
        assert "pagerank" in n.properties
        assert "betweenness" in n.properties
        assert "community" in n.properties


def test_contradiction_becomes_a_contradicts_edge() -> None:
    result = build(CONTRA)
    contradicts = [e for e in result.edges if e.predicate == "CONTRADICTS"]
    assert contradicts, "opposite-polarity claims should yield a CONTRADICTS edge"
    e = contradicts[0]
    assert e.subject.startswith("claim:") and e.object.startswith("claim:")
    assert str(e.tag) == "INFERRED"
    assert e.source_spans
