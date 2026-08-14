"""Structural link prediction (L7) — deterministic overlap scoring + engine wiring."""

from textgraph.l7_analytics.link_prediction import predict_links
from textgraph.l8_retrieval.engine import QueryEngine
from textgraph.store.base import ConfidenceTag, Edge, Node


def _rel(a: str, b: str) -> Edge:
    return Edge(
        edge_id=f"edge:{a}:{b}",
        subject=a,
        predicate="ASSOCIATED_WITH",
        object=b,
        tag=ConfidenceTag.EXTRACTED,
        confidence=0.9,
    )


def test_predicts_the_closing_triangle() -> None:
    # a-c, b-c, a-d, b-d: a and b share two neighbours (c, d) but aren't linked -> top prediction.
    adj = {"a": ["c", "d"], "b": ["c", "d"], "c": ["a", "b"], "d": ["a", "b"]}
    preds = predict_links(adj, k=5)
    assert preds, "expected at least one prediction"
    top = preds[0]
    assert {top.source, top.target} == {"a", "b"}
    assert set(top.shared) == {"c", "d"}
    assert top.score > 0


def test_no_prediction_between_already_connected_nodes() -> None:
    adj = {"a": ["b", "c"], "b": ["a", "c"], "c": ["a", "b"]}  # a triangle, fully connected
    assert predict_links(adj, k=5) == []


def test_anchor_scopes_predictions_to_one_node() -> None:
    adj = {"a": ["c", "d"], "b": ["c", "d"], "c": ["a", "b"], "d": ["a", "b"], "x": []}
    preds = predict_links(adj, k=5, anchor="a")
    assert preds and all("a" in (p.source, p.target) for p in preds)
    assert predict_links(adj, k=5, anchor="x") == []  # isolated anchor -> nothing


def test_index_choices_are_deterministic() -> None:
    adj = {"a": ["c", "d"], "b": ["c", "d"], "c": ["a", "b"], "d": ["a", "b"]}
    for index in ("adamic_adar", "common_neighbors", "resource_allocation"):
        assert predict_links(adj, index=index) == predict_links(adj, index=index)


def test_engine_predict_links_resolves_names() -> None:
    nodes = [
        Node("entity:a", ("Entity",), {"name": "Acme"}),
        Node("entity:b", ("Entity",), {"name": "Beta"}),
        Node("entity:c", ("Entity",), {"name": "Carol"}),
        Node("entity:d", ("Entity",), {"name": "Dave"}),
    ]
    edges = [
        _rel("entity:a", "entity:c"),
        _rel("entity:b", "entity:c"),
        _rel("entity:a", "entity:d"),
        _rel("entity:b", "entity:d"),
    ]
    preds = QueryEngine(nodes, edges).predict_links(k=5)
    assert preds
    names = {preds[0]["source_name"], preds[0]["target_name"]}
    assert names == {"Acme", "Beta"}
    assert set(preds[0]["shared"]) == {"Carol", "Dave"}
