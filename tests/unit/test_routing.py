"""Sprint 2.2 tests: deterministic per-query retrieval routing."""

from textgraph.l8_retrieval.routing import STRATEGY, classify_query, route


def test_classify_covers_each_intent() -> None:
    cases = {
        "MATCH (a)-[:CONTROLS]->(b) RETURN a.name": "gql",
        "how is Acme connected to Delta Trust": "path",
        "why does Acme control Gamma": "why",
        "what is Acme related to": "neighbors",
        "timeline of Acme Corp": "timeline",
        "are there contradictions": "contradictions",
        "what communities exist": "communities",
        "how many entities": "stats",
        "who moved the money": "reason",  # default
    }
    for q, expected in cases.items():
        assert classify_query(q) == expected, q


def test_forced_tool_overrides_and_is_validated() -> None:
    assert classify_query("anything", forced="search") == "search"
    assert classify_query("anything", forced="not-a-tool") == "reason"  # invalid -> safe default


def test_route_reports_strategy_family_and_reason() -> None:
    plan = route("how is Acme connected to Delta Trust")
    assert plan.tool == "path"
    assert plan.strategy == "graph-traversal"
    assert "connect" in plan.reason
    # Every routable tool maps to a known strategy family.
    for tool in STRATEGY:
        assert STRATEGY[tool] in {
            "structured-graph",
            "graph-traversal",
            "graph-analytics",
            "hybrid-lexical-graph",
            "hybrid-multi-tool",
        }


def test_routing_is_deterministic() -> None:
    q = "who transferred funds to whom"
    assert route(q).to_dict() == route(q).to_dict()
