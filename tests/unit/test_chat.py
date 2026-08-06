"""Phase A tests: the deterministic 'Ask' chat backend (routing + grounded answers)."""

import json
from pathlib import Path

from textgraph.console.api import route
from textgraph.console.chat import answer, classify
from textgraph.l8_retrieval import QueryEngine
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


def _engine() -> QueryEngine:
    r = build(DOCS)
    return QueryEngine(r.nodes, r.edges)


def test_classify_routes_by_intent() -> None:
    assert classify("how is Acme connected to Delta Trust") == "path"
    assert classify("why does Acme control Gamma") == "why"
    assert classify("timeline of Acme Corp") == "timeline"
    assert classify("MATCH (a)-[:CONTROLS]->(b) RETURN a.name") == "gql"
    assert classify("are there contradictions") == "contradictions"
    assert classify("what communities are there") == "communities"
    assert classify("who moved the money") == "reason"  # default
    assert classify("anything", forced="search") == "search"  # explicit override wins


def test_connection_question_returns_a_cited_path_with_highlights() -> None:
    ans = answer(_engine(), "how is Acme Corp connected to Delta Trust")
    assert ans.tool == "path"
    assert "Gamma Holdings" in ans.text  # the real connecting node
    assert ans.evidence  # cited
    assert len(ans.highlight_nodes) >= 2 and ans.highlight_edges  # graph gets highlighted


def test_why_question_is_grounded_and_cited() -> None:
    ans = answer(_engine(), "why does Acme Corp matter")
    assert ans.tool == "why"
    assert ans.evidence and ans.highlight_nodes
    assert ans.focus  # a primary entity to carry into the next turn


def test_multi_turn_follow_up_resolves_against_focus() -> None:
    eng = _engine()
    first = answer(eng, "tell me about Acme Corp")
    assert first.focus
    # A bare follow-up with no entity must resolve against the previous focus.
    follow = answer(eng, "why?", focus=first.focus)
    assert follow.focus == first.focus
    assert follow.tool == "why"


def test_reason_default_and_gql_passthrough() -> None:
    eng = _engine()
    r = answer(eng, "who transferred funds to whom")
    assert r.tool == "reason" and r.text and r.highlight_nodes
    g = answer(eng, "MATCH (a:Entity)-[:CONTROLS]->(b:Entity) RETURN a.name, b.name")
    assert g.tool == "gql" and "row" in g.text.lower()


def test_answer_is_deterministic() -> None:
    eng = _engine()
    q = "how is Acme Corp connected to Delta Trust"
    assert answer(eng, q).to_dict() == answer(eng, q).to_dict()


def test_empty_question_is_handled() -> None:
    assert answer(_engine(), "   ").tool == "auto"


def test_api_chat_route_returns_grounded_answer() -> None:
    eng = _engine()
    status, ctype, body = route(
        eng, "/api/chat", {"q": "how is Acme Corp connected to Delta Trust"}
    )
    assert status == 200 and "application/json" in ctype
    payload = json.loads(body)
    assert payload["tool"] == "path"
    assert payload["highlight"]["nodes"] and payload["highlight"]["edges"]
    assert payload["evidence"]
