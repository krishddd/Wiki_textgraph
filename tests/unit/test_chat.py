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


def test_roles_routing_and_answer() -> None:
    # "similar role" phrasing routes to the roles tool.
    assert classify("entities with a similar role to Acme Corp") == "roles"
    assert classify("structural role of Acme Corp") == "roles"
    eng = _engine()
    ans = answer(eng, "entities with a similar role to Acme Corp", tool="roles")
    assert ans.tool == "roles"
    assert not ans.abstained  # role similarity is not a factual claim -> never abstains
    # It highlights the anchor + peers on the canvas.
    assert ans.highlight_nodes


def test_open_question_stays_deterministic_without_an_llm() -> None:
    # No LLM endpoint configured -> the answer is the deterministic (templated) text, and
    # `narrated` is False. The offline moat is preserved.
    ans = answer(_engine(), "who transferred funds to whom")
    assert ans.tool in ("reason", "search")
    assert ans.narrated is False


def test_open_question_is_narrated_when_an_llm_is_available(monkeypatch) -> None:
    # When an LLM endpoint IS configured, an open question's terse text is recomposed as grounded
    # natural-language prose (narrated=True), while its citations are preserved.
    import textgraph.l4_llm_optional as l4
    import textgraph.l8_retrieval.narrate as narr
    from textgraph.console.chat import answer as _answer

    class _NL:
        def __init__(self, text, citations):
            self.text = text
            self.citations = citations

    def fake_compose(client, q, passages):
        cites = [c for _snip, cs in passages for c in cs][:2]
        return _NL("In plain English: the money moved from Acme Corp onward to Beta Ltd.", cites)

    monkeypatch.setattr(l4, "resolve_client", lambda cfg: object())  # non-None => available
    monkeypatch.setattr(narr, "narrate", fake_compose)

    ans = _answer(_engine(), "who moved the money")
    assert ans.narrated is True
    assert "plain English" in ans.text  # LLM prose, not the templated summary
    assert ans.evidence  # citations preserved under the prose


def test_forced_tool_is_not_auto_narrated(monkeypatch) -> None:
    # A user who explicitly picks a tool (not "auto") gets that tool's deterministic answer,
    # never a silent LLM rewrite.
    import textgraph.l4_llm_optional as l4

    monkeypatch.setattr(l4, "resolve_client", lambda cfg: object())
    ans = answer(_engine(), "who moved the money", tool="search")
    assert ans.narrated is False


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


def test_grounding_confidence_and_abstention() -> None:
    from textgraph.l8_retrieval.grounding import assess

    # Non-factual tools are always confident (empty aggregate is a real answer).
    assert assess("stats", evidence_count=0).abstain is False
    # A factual answer with no citations abstains.
    g0 = assess("why", evidence_count=0)
    assert g0.abstain is True and g0.confidence == 0.0
    # More cited spans -> higher confidence, no abstention.
    assert assess("search", evidence_count=4).confidence > 0.9


def test_chat_abstains_on_a_factual_query_with_no_evidence() -> None:
    ans = answer(_engine(), "qwxzptvbmnk", tool="search")  # matches no token in the corpus
    assert not ans.evidence  # genuinely unsupported
    assert ans.abstained is True
    assert "Insufficient evidence" in ans.text
    assert not ans.highlight_nodes  # nothing to highlight when we abstain


def test_chat_does_not_abstain_on_a_supported_answer() -> None:
    ans = answer(_engine(), "how is Acme Corp connected to Delta Trust")
    assert ans.abstained is False
    assert ans.confidence > 0.5 and ans.evidence


def test_search_entity_match_is_grounded_not_abstained() -> None:
    # Regression: an entity-only match must ground on its entity citations, not abstain
    # just because there was no passage chunk.
    ans = answer(_engine(), "Acme Corp", tool="search")
    assert ans.tool == "search"
    assert ans.abstained is False and ans.evidence and ans.highlight_nodes
