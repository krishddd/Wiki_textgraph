"""Ask dock Phase-A upgrades: session memory, suggestions, citation source, routing."""

import json
from pathlib import Path

from textgraph.console.api import route
from textgraph.console.session import ChatSession, SessionStore, Turn, resolve_followup
from textgraph.console.source import read_span
from textgraph.console.suggest import suggest
from textgraph.l8_retrieval import QueryEngine
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


def _engine(corpus: Path = DOCS) -> QueryEngine:
    r = build(corpus)
    return QueryEngine(r.nodes, r.edges)


# -- session / anaphora ---------------------------------------------------------------


def test_session_remembers_focus_and_bounds_history() -> None:
    s = ChatSession(max_turns=3)
    for i in range(5):
        s.remember(Turn(question=f"q{i}", tool="why", focus=f"e{i}", nodes=(f"e{i}",)))
    assert len(s.turns) == 3  # trimmed to the cap (G7)
    assert s.last_focus == "e4"
    assert s.recent_nodes()[0] == "e4"


def test_resolve_followup_substitutes_pronoun_with_remembered_entity() -> None:
    s = ChatSession()
    s.remember(Turn(question="why acme", tool="why", focus="entity:acme"))
    follow = resolve_followup(
        "who else is connected to them?",
        s,
        name_of=lambda nid: "Acme Corporation" if nid == "entity:acme" else "",
    )
    assert "Acme Corporation" in follow.question
    assert "them" not in follow.question.lower()
    assert follow.tool == "neighbors"  # "who else" -> one-hop expansion of the focus
    assert follow.resolved == "Acme Corporation"


def test_resolve_followup_noops_without_a_subject_or_pronoun() -> None:
    # No session -> unchanged.
    f1 = resolve_followup("who controls Beta Ltd?", None, name_of=lambda x: "X")
    assert f1.question == "who controls Beta Ltd?" and f1.tool is None
    # Session, but the question names its own subject (no pronoun) -> unchanged.
    s = ChatSession()
    s.remember(Turn(question="why acme", tool="why", focus="entity:acme"))
    f2 = resolve_followup("who controls Beta Ltd?", s, name_of=lambda x: "Acme")
    assert f2.question == "who controls Beta Ltd?"


def test_session_store_is_bounded_lru() -> None:
    store = SessionStore(max_sessions=2)
    a, b = store.get("a"), store.get("b")
    assert a is not None and b is not None
    b.remember(Turn(question="q", tool="stats"))  # give b state we can detect after eviction
    store.get("a")  # touch a so b is now the LRU
    store.get("c")  # evicts b (a and c remain)
    assert store.get("a") is a  # a survived: it was most-recently used, b was the LRU
    revived = store.get("b")
    assert revived is not b  # b was evicted; this is a fresh, empty session
    assert revived.turns == []


def test_chat_endpoint_threads_session_memory() -> None:
    eng = _engine()
    store = SessionStore()
    # First question establishes a focus.
    st, _, body = route(
        eng, "/api/chat", {"q": "why Acme Corporation", "session_id": "s1"}, sessions=store
    )
    first = json.loads(body)
    assert st == 200
    # A bare anaphoric follow-up should resolve against the remembered focus, not abstain
    # for lack of a subject.
    _, _, body2 = route(
        eng,
        "/api/chat",
        {"q": "who else is connected to them?", "session_id": "s1"},
        sessions=store,
    )
    second = json.loads(body2)
    if first.get("focus"):
        assert second["routing"]["focus"], second["routing"]
    # /api/ask is the documented alias for the same handler.
    st3, _, _ = route(eng, "/api/ask", {"q": "stats", "session_id": "s1"}, sessions=store)
    assert st3 == 200


# -- suggestions ----------------------------------------------------------------------


def test_suggestions_are_derived_from_the_answer() -> None:
    eng = _engine()
    _, _, body = route(eng, "/api/chat", {"q": "stats"}, sessions=SessionStore())
    ans = json.loads(body)
    assert isinstance(ans["suggestions"], list)
    assert len(ans["suggestions"]) <= 3
    assert all(isinstance(s, str) and s for s in ans["suggestions"])


def test_suggestions_empty_on_abstention() -> None:
    from textgraph.console.chat import ChatAnswer

    eng = _engine()
    abstained = ChatAnswer(text="no evidence", tool="why", abstained=True)
    assert suggest(eng, abstained) == []


# -- citation source click-through ----------------------------------------------------


def test_read_span_returns_verified_bytes_from_a_corpus() -> None:
    r = build(DOCS)
    eng = QueryEngine(r.nodes, r.edges)
    # Take a real cited edge span.
    span = next(s for e in r.edges for s in e.source_spans if e.tag.name != "GENERATED")
    out = read_span(eng, str(DOCS), span.doc_id, span.start, span.end, expected_hash=span.hash)
    assert out["available"] is True
    assert out["verified"] is True
    assert out["span"]  # the actual cited text
    assert "name" in out


def test_read_span_degrades_without_a_corpus() -> None:
    r = build(DOCS)
    eng = QueryEngine(r.nodes, r.edges)
    span = next(s for e in r.edges for s in e.source_spans)
    out = read_span(eng, None, span.doc_id, span.start, span.end)
    assert out["available"] is False
    assert out["reason"] == "no-corpus"


def test_source_endpoint_routes_with_corpus() -> None:
    r = build(DOCS)
    eng = QueryEngine(r.nodes, r.edges)
    span = next(s for e in r.edges for s in e.source_spans if e.tag.name != "GENERATED")
    st, _, body = route(
        eng,
        "/api/source",
        {"doc": span.doc_id, "start": str(span.start), "end": str(span.end), "hash": span.hash},
        source=str(DOCS),
    )
    assert st == 200
    assert json.loads(body)["available"] is True
