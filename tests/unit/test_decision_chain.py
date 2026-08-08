"""Decision-chain traversal + similarity (L8 decision-provenance queries)."""

from pathlib import Path

import pytest
from textgraph.cli import main
from textgraph.l8_retrieval import QueryEngine
from textgraph.pipeline import build

CHAIN = Path(__file__).parent.parent / "fixtures" / "corpora" / "decision_chain"


def _engine(corpus: Path = CHAIN) -> QueryEngine:
    r = build(corpus)
    return QueryEngine(r.nodes, r.edges)


# --- trace_decision_chain ----------------------------------------------------


def test_trace_returns_ancestors_and_descendants() -> None:
    res = _engine().trace_decision_chain("Byte-range citations").to_dict()
    assert res["found"] is True
    assert "ADR-0002" in res["decision"]["name"]
    # ADR-0001 is a precedent (ancestor); ADR-0003 was caused (descendant).
    anc = res["ancestors"]
    desc = res["descendants"]
    assert [h["relation"] for h in anc] == ["PRECEDENT_FOR"]
    assert "ADR-0001" in anc[0]["from_name"]
    assert [h["relation"] for h in desc] == ["CAUSED"]
    assert "ADR-0003" in desc[0]["to_name"]


def test_trace_hops_are_cited() -> None:
    res = _engine().trace_decision_chain("Byte-range citations").to_dict()
    for h in res["ancestors"] + res["descendants"]:
        assert h["citations"]  # every causal hop carries a re-verifiable span


def test_trace_unknown_decision_is_not_found() -> None:
    res = _engine().trace_decision_chain("zzzqqq wombat xylophone").to_dict()
    # BM25 returns nothing for a fully non-matching query -> not found.
    assert res["found"] is False
    assert res["decision"] is None


def test_trace_by_node_id() -> None:
    eng = _engine()
    did = next(
        n.node_id
        for n in eng._node.values()
        if "Decision" in n.labels and "ADR-0002" in n.properties["name"]
    )
    res = eng.trace_decision_chain(did).to_dict()
    assert res["found"] is True and res["decision"]["decision_id"] == did


def test_trace_is_deterministic() -> None:
    eng = _engine()
    a = eng.trace_decision_chain("Byte-range citations").to_dict()
    b = eng.trace_decision_chain("Byte-range citations").to_dict()
    assert a == b


def test_trace_depth_bound_is_respected() -> None:
    # With max_hops=0 no hop is emitted, but the decision itself still resolves.
    res = _engine().trace_decision_chain("Byte-range citations", max_hops=0).to_dict()
    assert res["found"] is True
    assert res["ancestors"] == [] and res["descendants"] == []


# --- find_similar_decisions --------------------------------------------------


def test_find_similar_ranks_by_statement_relevance() -> None:
    res = _engine().find_similar_decisions("byte-range citation re-verify", k=3).to_dict()
    assert res["hits"]
    assert "citation" in res["hits"][0]["name"].lower()
    assert all(h["citations"] for h in res["hits"])  # every hit cited


def test_find_similar_respects_k() -> None:
    res = _engine().find_similar_decisions("retention citation tool", k=1).to_dict()
    assert len(res["hits"]) == 1


def test_find_similar_no_match_is_empty() -> None:
    res = _engine().find_similar_decisions("zzzqqq nonexistent", k=5).to_dict()
    assert res["hits"] == []


# --- CLI ---------------------------------------------------------------------


def test_trace_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["trace-decision", str(CHAIN), "Byte-range citations"]) == 0
    out = capsys.readouterr().out
    assert "PRECEDENT_FOR" in out and "CAUSED" in out
    assert "ADR-0001" in out and "ADR-0003" in out


def test_trace_cli_no_match(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["trace-decision", str(CHAIN), "totally unrelated zzz"]) == 0
    assert "no decision matched" in capsys.readouterr().out


def test_find_decisions_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["find-decisions", str(CHAIN), "byte-range citation", "-k", "2"]) == 0
    out = capsys.readouterr().out
    assert "decisions similar to" in out
    assert "citation" in out.lower()


def test_find_decisions_cli_missing_path() -> None:
    assert main(["find-decisions", str(CHAIN / "nope"), "x"]) == 2
