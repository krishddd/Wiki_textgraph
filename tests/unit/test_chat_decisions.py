"""Ask-chat wiring for the decision/conflict tools (routing + grounded answers)."""

from pathlib import Path

import pytest
from textgraph.console.chat import answer, classify
from textgraph.l8_retrieval import QueryEngine
from textgraph.pipeline import build

CONFLICT = Path(__file__).parent.parent / "fixtures" / "corpora" / "conflict"
CHAIN = Path(__file__).parent.parent / "fixtures" / "corpora" / "decision_chain"


def _engine(corpus: Path) -> QueryEngine:
    r = build(corpus)
    return QueryEngine(r.nodes, r.edges)


# --- routing -----------------------------------------------------------------


def test_conflict_and_contradiction_route_separately() -> None:
    assert classify("are there any conflicts") == "conflicts"
    assert classify("are there contradictions") == "contradictions"


def test_decision_questions_route_to_trace_or_search() -> None:
    assert classify("what led to this decision") == "trace"
    assert classify("trace the decision lineage") == "trace"
    assert classify("find decisions about retention") == "decisions"
    assert classify("which decision covers citations") == "decisions"


def test_forced_tools_are_honored() -> None:
    assert classify("anything", forced="conflicts") == "conflicts"
    assert classify("anything", forced="trace") == "trace"
    assert classify("anything", forced="decisions") == "decisions"


# --- answers -----------------------------------------------------------------


def test_conflicts_answer_is_cited_and_highlighted() -> None:
    ans = answer(_engine(CONFLICT), "are there conflicts")
    assert ans.tool == "conflicts"
    assert "conflict(s)" in ans.text and "HIGH" in ans.text
    assert ans.evidence  # contending claims are cited
    assert ans.highlight_nodes  # subject/objects resolve onto the canvas
    assert not ans.abstained and ans.confidence == 1.0  # aggregate tool never abstains


def test_conflicts_answer_empty_is_not_an_abstention() -> None:
    ans = answer(_engine(CHAIN), "are there conflicts")  # no single-truth conflicts here
    assert ans.tool == "conflicts"
    assert "No single-truth conflicts" in ans.text
    assert not ans.abstained


def test_trace_answer_shows_ancestors_and_effects() -> None:
    ans = answer(_engine(CHAIN), "what led to the byte-range citations decision")
    assert ans.tool == "trace"
    assert "precedent" in ans.text and "effect" in ans.text
    assert ans.evidence  # every hop cited
    directions = {d["direction"] for d in ans.detail}
    assert directions == {"ancestor", "descendant"}


def test_trace_answer_no_match() -> None:
    # "rationale" routes to a decision tool but appears in no statement, so BM25 finds nothing.
    ans = answer(_engine(CHAIN), "trace the rationale lineage for zzzqqq wombat")
    assert ans.tool == "trace"
    assert "No matching decision" in ans.text


def test_find_decisions_answer_is_ranked_and_cited() -> None:
    ans = answer(_engine(CHAIN), "find decisions about citation tooling")
    assert ans.tool == "decisions"
    assert "decision(s) matching" in ans.text
    assert ans.evidence
    assert ans.detail and "score" in ans.detail[0]


def test_answers_are_deterministic() -> None:
    eng = _engine(CONFLICT)
    a = answer(eng, "are there conflicts").to_dict()
    b = answer(eng, "are there conflicts").to_dict()
    assert a == b


def test_narrate_tool_is_registered_and_selectable() -> None:
    from textgraph.l8_retrieval.routing import TOOLS

    assert "narrate" in TOOLS
    assert classify("anything", forced="narrate") == "narrate"


def test_narrate_without_llm_endpoint_is_graceful(monkeypatch: pytest.MonkeyPatch) -> None:
    # No LLM env configured -> a clear message, never a fabricated answer.
    for var in ("TEXTGRAPH_LLM_API_KEY", "API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    ans = answer(_engine(CONFLICT), "summarise the conflicts", tool="narrate")
    assert ans.tool == "narrate"
    assert "endpoint" in ans.text.lower()
    assert not ans.abstained
